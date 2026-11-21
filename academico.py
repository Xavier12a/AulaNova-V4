"""Calificaciones por tareas y bimestre de AulaNova."""

import os
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from flask import abort, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from db import get_db_connection
from rutas_academicas import app


BIMESTRES = tuple(f"Bimestre {n}" for n in range(1, 5))


# ---------------------------------------------------------------------
# Base de datos: promedio automático y conservación de ajustes manuales.
# ---------------------------------------------------------------------

def sql_actualizar_promedios(curso):
    # Recalcula solo los promedios automáticos (es_manual = 0) sin pisar ajustes manuales
    return f"""
        DELETE FROM Calificaciones
        WHERE id_curso = {curso} AND es_manual = 0;

        INSERT INTO Calificaciones
            (id_alumno, id_curso, periodo, nota, es_manual)
        SELECT p.id_alumno, p.id_curso, p.periodo, p.promedio, 0
        FROM PromediosTareas p
        WHERE p.id_curso = {curso}
          AND NOT EXISTS (
              SELECT 1 FROM Calificaciones c
              WHERE c.id_alumno = p.id_alumno
                AND c.id_curso = p.id_curso
                AND c.periodo = p.periodo
          );
    """


def preparar_notas():
    # Asegura columnas, tabla de ceros explícitos, vista de promedios y triggers SQLite
    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")

        columnas_tareas = {
            fila["name"] for fila in conn.execute("PRAGMA table_info(Tareas)")
        }
        columnas_notas = {
            fila["name"] for fila in conn.execute("PRAGMA table_info(Calificaciones)")
        }
        columnas_entregas = {
            fila["name"] for fila in conn.execute("PRAGMA table_info(EntregasTareas)")
        }

        if "periodo" not in columnas_tareas:
            conn.execute("ALTER TABLE Tareas ADD COLUMN periodo TEXT")

        if "comentario_docente" not in columnas_entregas:
            conn.execute("ALTER TABLE EntregasTareas ADD COLUMN comentario_docente TEXT")

        if "es_manual" not in columnas_notas:
            conn.execute("""
                ALTER TABLE Calificaciones
                ADD COLUMN es_manual INTEGER NOT NULL DEFAULT 1
            """)
            conn.execute("""
                UPDATE Calificaciones SET es_manual = 0 WHERE nota IS NULL
            """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS CerosSinEntrega (
                id_tarea INTEGER NOT NULL,
                id_alumno INTEGER NOT NULL,
                PRIMARY KEY (id_tarea, id_alumno)
            )
        """)

        # Vista que consolida entregas calificadas y ceros asignados por no presentación
        conn.execute("""
            CREATE VIEW IF NOT EXISTS PromediosTareas AS
            SELECT t.id_curso, t.periodo, n.id_alumno,
                   ROUND(AVG(n.nota), 1) AS promedio
            FROM Tareas t
            JOIN (
                SELECT id_tarea, id_alumno, nota_tarea AS nota
                FROM EntregasTareas
                WHERE nota_tarea IS NOT NULL

                UNION ALL

                SELECT z.id_tarea, z.id_alumno, 0
                FROM CerosSinEntrega z
                WHERE NOT EXISTS (
                    SELECT 1 FROM EntregasTareas e
                    WHERE e.id_tarea = z.id_tarea
                      AND e.id_alumno = z.id_alumno
                )
            ) n ON n.id_tarea = t.id_tarea
            WHERE t.periodo IS NOT NULL
            GROUP BY t.id_curso, t.periodo, n.id_alumno
        """)

        # Triggers para mantener sincronizada la tabla Calificaciones ante cambios en entregas
        for tabla in ("EntregasTareas", "CerosSinEntrega"):
            for evento in ("INSERT", "DELETE", "UPDATE"):
                referencia = "OLD" if evento == "DELETE" else "NEW"
                curso = (
                    "(SELECT id_curso FROM Tareas "
                    f"WHERE id_tarea = {referencia}.id_tarea)"
                )
                antes = ""
                if tabla == "EntregasTareas" and evento == "INSERT":
                    # Si el alumno entrega después de recibir 0, se retira el cero hasta revisar
                    antes = """
                        DELETE FROM CerosSinEntrega
                        WHERE id_tarea = NEW.id_tarea
                          AND id_alumno = NEW.id_alumno;
                    """

                conn.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS prom_{tabla}_{evento}
                    AFTER {evento} ON {tabla}
                    BEGIN
                        {antes}
                        {sql_actualizar_promedios(curso)}
                    END
                """)

        conn.execute(f"""
            CREATE TRIGGER IF NOT EXISTS prom_periodo
            AFTER UPDATE OF periodo ON Tareas
            BEGIN
                {sql_actualizar_promedios("NEW.id_curso")}
            END
        """)

        conn.execute(f"""
            CREATE TRIGGER IF NOT EXISTS prom_borrar_tarea
            AFTER DELETE ON Tareas
            BEGIN
                DELETE FROM CerosSinEntrega WHERE id_tarea = OLD.id_tarea;
                {sql_actualizar_promedios("OLD.id_curso")}
            END
        """)


preparar_notas()


# ---------------------------------------------------------------------
# Funciones compartidas.
# ---------------------------------------------------------------------

def exigir_docente():
    if session.get("id_rol") != 2:
        abort(403)


def obtener_curso(conn, id_curso):
    # Verifica que el curso exista y pertenezca al docente autenticado
    curso = conn.execute("""
        SELECT * FROM Cursos WHERE id_curso = ? AND id_docente = ?
    """, (id_curso, session["id_usuario"])).fetchone()
    if curso is None:
        abort(404)
    return curso


def obtener_usuario(conn):
    return conn.execute("""
        SELECT nombres, apellidos FROM Usuarios WHERE id_usuario = ?
    """, (session["id_usuario"],)).fetchone()


def obtener_tarea(conn, id_tarea):
    # Verifica que la tarea pertenezca a un curso dictado por el docente actual
    tarea = conn.execute("""
        SELECT t.*, c.nombre_curso, c.grado, c.seccion
        FROM Tareas t
        JOIN Cursos c ON c.id_curso = t.id_curso
        WHERE t.id_tarea = ? AND c.id_docente = ?
    """, (id_tarea, session["id_usuario"])).fetchone()
    if tarea is None:
        abort(404)
    return tarea


def leer_nota(texto):
    # Valida que la nota sea un número entre 0 y 20 con máximo un decimal
    texto = (texto or "").strip().replace(",", ".")
    if texto == "":
        return None
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        raise ValueError("La nota debe ser un número.") from None

    if not valor.is_finite() or not 0 <= valor <= 20:
        raise ValueError("La nota debe estar entre 0 y 20.")
    if valor != valor.quantize(Decimal("0.1")):
        raise ValueError("Usa como máximo un decimal en la nota.")
    return float(valor)


def volver_notas(id_curso, periodo):
    return redirect(url_for("docente_curso", id_curso=id_curso, periodo=periodo))


def volver_tareas(id_curso):
    return redirect(url_for("docente_tareas", id_curso=id_curso))


def volver_entregas(id_tarea):
    return redirect(url_for("docente_ver_entregas", id_tarea=id_tarea))


# ---------------------------------------------------------------------
# Gestionar notas: promedio de tareas, ajuste manual y nota final.
# ---------------------------------------------------------------------

def notas_del_curso(id_curso):
    exigir_docente()

    if request.method == "POST":
        periodo = request.form.get("periodo")
    else:
        periodo = request.args.get("periodo", "Bimestre 1")

    if periodo not in BIMESTRES:
        abort(400, "Bimestre inválido.")

    try:
        with closing(get_db_connection()) as conn, conn:
            if request.method == "POST":
                conn.execute("BEGIN IMMEDIATE")

            curso = obtener_curso(conn, id_curso)
            usuario = obtener_usuario(conn)
            alumnos = conn.execute("""
                SELECT u.id_usuario, u.dni, u.nombres, u.apellidos,
                       p.promedio,
                       CASE WHEN c.es_manual = 1 THEN c.nota END AS ajuste,
                       CASE WHEN c.es_manual = 1 THEN c.nota
                            ELSE p.promedio END AS nota_final
                FROM Usuarios u
                LEFT JOIN PromediosTareas p
                  ON p.id_alumno = u.id_usuario
                 AND p.id_curso = ? AND p.periodo = ?
                LEFT JOIN Calificaciones c
                  ON c.id_alumno = u.id_usuario
                 AND c.id_curso = ? AND c.periodo = ?
                WHERE u.id_rol = 3 AND u.grado = ? AND u.seccion = ?
                ORDER BY u.apellidos, u.nombres
            """, (
                id_curso, periodo, id_curso, periodo,
                curso["grado"], curso["seccion"]
            )).fetchall()

            if request.method == "POST":
                for alumno in alumnos:
                    ident = alumno["id_usuario"]
                    clave = f"ajuste_{ident}"
                    if clave not in request.form:
                        continue

                    original = leer_nota(request.form.get(f"anterior_{ident}"))
                    nueva = leer_nota(request.form[clave])

                    if nueva == original:
                        continue
                    # Control optimista: evita sobrescribir cambios hechos en otra pestaña
                    if alumno["ajuste"] != original:
                        raise ValueError(
                            "Una nota cambió en otra ventana. "
                            "Revisa los valores y vuelve a guardar."
                        )

                    if nueva is not None:
                        conn.execute("""
                            INSERT INTO Calificaciones
                                (id_alumno, id_curso, periodo, nota, es_manual)
                            VALUES (?, ?, ?, ?, 1)
                            ON CONFLICT(id_alumno, id_curso, periodo)
                            DO UPDATE SET nota = excluded.nota, es_manual = 1
                        """, (ident, id_curso, periodo, nueva))
                    else:
                        # Si se borra el ajuste manual, se restaura el promedio de tareas
                        conn.execute("""
                            DELETE FROM Calificaciones
                            WHERE id_alumno = ? AND id_curso = ? AND periodo = ?
                        """, (ident, id_curso, periodo))

                        if alumno["promedio"] is not None:
                            conn.execute("""
                                INSERT INTO Calificaciones
                                    (id_alumno, id_curso, periodo, nota, es_manual)
                                VALUES (?, ?, ?, ?, 0)
                            """, (ident, id_curso, periodo, alumno["promedio"]))

                flash("Calificaciones del bimestre guardadas.")
                return volver_notas(id_curso, periodo)

    except ValueError as error:
        flash(str(error))
        return volver_notas(id_curso, periodo)

    return render_template(
        "Docente/docente_curso.html",
        usuario=usuario, curso=curso, alumnos=alumnos,
        periodo=periodo, bimestres=BIMESTRES
    )


# ---------------------------------------------------------------------
# Publicar actividades y asignar bimestre a las anteriores.
# ---------------------------------------------------------------------

def tareas_del_curso(id_curso):
    exigir_docente()
    hoy = date.today().isoformat()
    archivo_guardado = None

    try:
        with closing(get_db_connection()) as conn, conn:
            curso = obtener_curso(conn, id_curso)
            usuario = obtener_usuario(conn)

            if request.method == "POST":
                periodo = request.form.get("periodo")
                if periodo not in BIMESTRES:
                    raise ValueError("Selecciona el bimestre de la actividad.")

                # Permite reasignar el bimestre de una tarea ya existente
                if request.form.get("accion") == "asignar_periodo":
                    id_tarea = request.form.get("id_tarea", type=int)
                    cambio = conn.execute("""
                        UPDATE Tareas SET periodo = ?
                        WHERE id_tarea = ? AND id_curso = ?
                    """, (periodo, id_tarea, id_curso))
                    if cambio.rowcount != 1:
                        abort(404)
                    flash("Bimestre actualizado. Se recalcularon los promedios.")
                    return volver_tareas(id_curso)

                titulo = request.form.get("titulo", "").strip()
                descripcion = request.form.get("descripcion", "").strip()
                fecha = request.form.get("fecha_entrega", "")
                if not titulo or not descripcion:
                    raise ValueError("Completa el título y las instrucciones.")
                try:
                    limite = date.fromisoformat(fecha)
                except ValueError:
                    raise ValueError("Selecciona una fecha de entrega válida.") from None
                if limite < date.today():
                    raise ValueError("La fecha de entrega debe ser hoy o posterior.")

                nombre_archivo = None
                archivo = request.files.get("archivo")
                if archivo and archivo.filename:
                    nombre = secure_filename(archivo.filename) or "adjunto"
                    nombre_archivo = f"{uuid4().hex}_{nombre}"
                    archivo_guardado = os.path.join(
                        app.config["UPLOAD_FOLDER"], nombre_archivo
                    )
                    archivo.save(archivo_guardado)

                conn.execute("""
                    INSERT INTO Tareas
                        (id_curso, titulo, descripcion, fecha_entrega, archivo_adjunto, periodo)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (id_curso, titulo, descripcion, limite.isoformat(), nombre_archivo, periodo))
                flash("Actividad publicada correctamente.")
                return volver_tareas(id_curso)

            total = conn.execute("""
                SELECT COUNT(*) FROM Usuarios
                WHERE id_rol = 3 AND grado = ? AND seccion = ?
            """, (curso["grado"], curso["seccion"])).fetchone()[0]

            tareas = conn.execute("""
                SELECT t.*,
                       COUNT(e.id_entrega) AS entregadas,
                       COUNT(CASE WHEN e.id_entrega IS NOT NULL
                                       AND e.nota_tarea IS NULL THEN 1 END) AS por_calificar
                FROM Tareas t
                LEFT JOIN EntregasTareas e ON e.id_tarea = t.id_tarea
                WHERE t.id_curso = ?
                GROUP BY t.id_tarea
                ORDER BY t.id_tarea DESC
            """, (id_curso,)).fetchall()

    except ValueError as error:
        flash(str(error))
        return volver_tareas(id_curso)
    except Exception:
        # Limpia el archivo subido si falla la inserción en base de datos
        if archivo_guardado and os.path.isfile(archivo_guardado):
            os.remove(archivo_guardado)
        raise

    return render_template(
        "Docente/tareas_docente.html", usuario=usuario, curso=curso,
        tareas=tareas, total=total, hoy=hoy, bimestres=BIMESTRES
    )


# ---------------------------------------------------------------------
# Revisar entregas. Sin entrega se puede registrar explícitamente un cero.
# ---------------------------------------------------------------------

def calificar_entregas(id_tarea):
    exigir_docente()

    try:
        with closing(get_db_connection()) as conn, conn:
            if request.method == "POST":
                conn.execute("BEGIN IMMEDIATE")

            tarea = obtener_tarea(conn, id_tarea)
            usuario = obtener_usuario(conn)

            alumnos = conn.execute("""
                SELECT u.id_usuario, u.dni, u.nombres, u.apellidos,
                       e.id_entrega, e.archivo_alumno, e.fecha_entrega,
                       e.comentario_docente,
                       CASE WHEN e.id_entrega IS NOT NULL THEN e.nota_tarea
                            WHEN z.id_alumno IS NOT NULL THEN 0 END AS nota
                FROM Usuarios u
                LEFT JOIN EntregasTareas e
                  ON e.id_alumno = u.id_usuario AND e.id_tarea = ?
                LEFT JOIN CerosSinEntrega z
                  ON z.id_alumno = u.id_usuario AND z.id_tarea = ?
                WHERE u.id_rol = 3 AND u.grado = ? AND u.seccion = ?
                ORDER BY u.apellidos, u.nombres
            """, (
                id_tarea, id_tarea, tarea["grado"], tarea["seccion"]
            )).fetchall()

            if request.method == "POST":
                for alumno in alumnos:
                    ident = alumno["id_usuario"]
                    clave = f"nota_{ident}"
                    if clave not in request.form:
                        continue

                    original = leer_nota(request.form.get(f"anterior_{ident}"))
                    nueva = leer_nota(request.form[clave])
                    comentario_nuevo = (request.form.get(f"comentario_{ident}") or "").strip() or None
                    comentario_actual = (alumno["comentario_docente"] or "").strip() or None

                    if original == nueva and comentario_nuevo == comentario_actual:
                        continue
                    # Verifica que ni la nota ni el estado de entrega cambiaran durante la revisión
                    if alumno["nota"] != original:
                        raise ValueError(
                            "Otra ventana cambió una calificación. "
                            "Revisa la lista y vuelve a guardar."
                        )
                    entrega_vista = request.form.get(f"entrega_{ident}", "")
                    entrega_actual = str(alumno["id_entrega"] or "")
                    if entrega_vista != entrega_actual:
                        raise ValueError(
                            "Se recibió una entrega mientras calificabas. "
                            "Revísala antes de guardar."
                        )

                    if alumno["id_entrega"] is not None:
                        conn.execute("""
                            UPDATE EntregasTareas
                            SET nota_tarea = ?, comentario_docente = ?
                            WHERE id_tarea = ? AND id_alumno = ?
                        """, (nueva, comentario_nuevo, id_tarea, ident))
                    elif nueva is None:
                        conn.execute("""
                            DELETE FROM CerosSinEntrega
                            WHERE id_tarea = ? AND id_alumno = ?
                        """, (id_tarea, ident))
                    elif nueva == 0:
                        conn.execute("""
                            INSERT OR IGNORE INTO CerosSinEntrega(id_tarea, id_alumno)
                            VALUES (?, ?)
                        """, (id_tarea, ident))
                    else:
                        raise ValueError(
                            f"{alumno['nombres']} {alumno['apellidos']} no tiene entrega. "
                            "Puedes dejar la nota en blanco o registrar 0."
                        )

                flash("Calificaciones y comentarios guardados.")
                return volver_entregas(id_tarea)

    except ValueError as error:
        flash(str(error))
        return volver_entregas(id_tarea)

    return render_template(
        "Docente/docente_entregas.html",
        usuario=usuario, tarea=tarea, alumnos_entregas=alumnos
    )


# ---------------------------------------------------------------------
# Filtro directo para leer el comentario del docente desde la BD.
# ---------------------------------------------------------------------

@app.template_filter("comentario_entrega")
def filtro_comentario_entrega(id_entrega):
    if not id_entrega:
        return None
    try:
        with closing(get_db_connection()) as conn:
            fila = conn.execute("""
                SELECT comentario_docente FROM EntregasTareas WHERE id_entrega = ?
            """, (id_entrega,)).fetchone()
        return fila["comentario_docente"] if fila and fila["comentario_docente"] else None
    except Exception:
        return None


# Se conservan las URL que ya utilizan los botones y enlaces de AulaNova.
app.view_functions["docente_curso"] = notas_del_curso
app.view_functions["docente_tareas"] = tareas_del_curso
app.view_functions["docente_ver_entregas"] = calificar_entregas