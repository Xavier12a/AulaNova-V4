"""Carga y limpieza de los datos ficticios de demostración de AulaNova."""

import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta

from flask import flash, redirect, request, session, url_for
from werkzeug.security import generate_password_hash

from db import get_db_connection


GRADO_DEMO = "1ro de Primaria"
SECCION_DEMO = "A"

# Identidades inventadas para la demostración.
DOCENTES_DEMO = (
    (
        "Elena Mar",
        "Brisalta Prado",
        ("MATEMÁTICA", "COMUNICACIÓN", "PERSONAL SOCIAL", "CIENCIA Y TECNOLOGÍA"),
    ),
    ("Bruno Elías", "Valleclaro Roble", ("ARTE Y CULTURA",)),
    ("Nora Isabel", "Monteluz Vera", ("EDUCACIÓN FÍSICA",)),
    ("Iván Darío", "Pradoazul Solís", ("EDUCACIÓN RELIGIOSA", "INGLÉS")),
)

ALUMNOS_DEMO = (
    ("Luna Isabel", "Solalba Ríos"),
    ("Mateo Andrés", "Valleclaro Paz"),
    ("Alma Lucía", "Monteluz Vera"),
    ("Nicolás Elías", "Brisalta León"),
    ("Vera Emilia", "Pradoazul Gil"),
    ("Leo Daniel", "Ríoclaro Soto"),
    ("Maia Elena", "Lomaluz Pérez"),
    ("Gael Martín", "Campoluna Díaz"),
    ("Clara Inés", "Solverde Peña"),
    ("Simón Ariel", "Vallealto Cruz"),
    ("Abril Sofía", "Montelago Rey"),
    ("Teo Gabriel", "Pradoclaro Luna"),
    ("Iris Valentina", "Brisaverde Mora"),
    ("Ian Sebastián", "Cielomar Vidal"),
    ("Eva Luciana", "Lomazul Ortiz"),
    ("Noé Adrián", "Altolago Ruiz"),
    ("Zoe Camila", "Solcampo Lara"),
    ("Hugo Benjamín", "Montebrisa Cano"),
)

# Los plazos distintos permiten probar la pregunta del búho «¿Qué vence primero?».
TAREAS_DEMO = (
    (
        "MATEMÁTICA",
        "Contamos y sumamos hasta diez",
        "Dibuja tres manzanas y dos manzanas más. Cuenta cuántas hay, "
        "escribe la suma y sube una foto de tu cuaderno.",
        1,
    ),
    (
        "COMUNICACIÓN",
        "Mi cuento favorito",
        "Escucha un cuento corto. Dibuja a tu personaje favorito "
        "y escribe su nombre con ayuda de tu familia.",
        3,
    ),
    (
        "CIENCIA Y TECNOLOGÍA",
        "Observamos una planta",
        "Dibuja una planta, señala la raíz, el tallo y las hojas. "
        "Escribe qué necesita para crecer y sube una foto de tu trabajo.",
        5,
    ),
)

AVISOS_DEMO = (
    (
        f"Reunión de familias de {GRADO_DEMO} - sección {SECCION_DEMO}",
        "Invitamos a las familias del salón a revisar la libreta del "
        "segundo bimestre. Cada familia puede consultarla desde su portal "
        "y llevar sus preguntas a la reunión del aula.",
        "Reunión",
        "Estudiantes y Familias",
    ),
    (
        "Revisión de calificaciones del segundo bimestre",
        "Se solicita a los docentes revisar las calificaciones registradas "
        "y verificar que correspondan al curso, salón y bimestre correctos.",
        "Urgente",
        "Solo Docentes",
    ),
    (
        "Feria de trabajos de primaria",
        "La comunidad educativa está invitada a conocer los trabajos de "
        "Matemática, Arte y Ciencia elaborados por los estudiantes de primaria.",
        "Académico",
        "Toda la Comunidad",
    ),
)


def registrar_rutas_demo(app):
    app.add_url_rule(
        "/admin/cargar-datos-prueba",
        view_func=cargar_datos_prueba,
        methods=["POST"],
    )
    app.add_url_rule(
        "/admin/limpiar-datos-prueba",
        view_func=limpiar_datos_prueba,
        methods=["POST"],
    )


def obtener_usuario_demo(conn, numero, nombres, apellidos, rol):
    es_docente = rol == 2
    prefijo = "98" if es_docente else "99"
    codigo = f"{prefijo}{numero:06d}"
    correo = f"{codigo}@example.invalid"
    grado = None if es_docente else GRADO_DEMO
    seccion = None if es_docente else SECCION_DEMO

    filas = conn.execute(
        """
        SELECT id_usuario, nombres, apellidos, dni, correo, id_rol, grado, seccion
        FROM Usuarios
        WHERE dni = ? OR correo = ?
        """,
        (codigo, correo),
    ).fetchall()

    if not filas:
        cursor = conn.execute(
            """
            INSERT INTO Usuarios (
                nombres, apellidos, correo, password, dni,
                grado, seccion, id_rol, estado
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                nombres,
                apellidos,
                correo,
                generate_password_hash(codigo),
                codigo,
                grado,
                seccion,
                rol,
            ),
        )
        return cursor.lastrowid

    usuario = filas[0]
    misma_cuenta = (
        len(filas) == 1
        and usuario["dni"] == codigo
        and usuario["correo"] == correo
        and usuario["id_rol"] == rol
        and usuario["grado"] == grado
        and usuario["seccion"] == seccion
    )

    etiqueta = "Docente" if es_docente else "Estudiante"
    nombre_anterior = (f"{etiqueta} {numero:02d}", "Demostración")
    nombre_guardado = (usuario["nombres"], usuario["apellidos"])

    if not misma_cuenta or nombre_guardado not in (
        (nombres, apellidos),
        nombre_anterior,
    ):
        raise ValueError(
            f"El código {codigo} ya pertenece a otra cuenta o a otro salón. "
            "La carga se canceló sin modificar los datos."
        )

    # Conserva la contraseña y los registros si la cuenta de prueba ya existía.
    if nombre_guardado == nombre_anterior:
        conn.execute(
            """
            UPDATE Usuarios
            SET nombres = ?, apellidos = ?
            WHERE id_usuario = ?
            """,
            (nombres, apellidos, usuario["id_usuario"]),
        )

    return usuario["id_usuario"]


def obtener_curso_demo(conn, nombre, id_docente):
    curso = conn.execute(
        """
        SELECT id_curso, id_docente
        FROM Cursos
        WHERE nombre_curso = ? AND grado = ? AND seccion = ?
        """,
        (nombre, GRADO_DEMO, SECCION_DEMO),
    ).fetchone()

    if curso:
        if curso["id_docente"] != id_docente:
            raise ValueError(
                f"{nombre} de {GRADO_DEMO}, sección {SECCION_DEMO}, "
                "ya existe con otra asignación docente. "
                "Usa una copia de prueba nueva para cargar la demostración."
            )
        return curso["id_curso"]

    cursor = conn.execute(
        """
        INSERT INTO Cursos (nombre_curso, grado, seccion, id_docente)
        VALUES (?, ?, ?, ?)
        """,
        (nombre, GRADO_DEMO, SECCION_DEMO, id_docente),
    )
    return cursor.lastrowid


def cargar_asistencia_demo(conn, alumnos, hoy):
    # Carga cinco días de lunes a viernes. Hoy queda libre para la exposición.
    fecha = hoy
    dias_registrados = 0

    while dias_registrados < 5:
        fecha -= timedelta(days=1)

        if fecha.weekday() >= 5:
            continue

        for numero, id_alumno in alumnos.items():
            turno = (numero + dias_registrados) % 13

            if turno == 0:
                estado = "Tardanza"
                observacion = "Llegó después del inicio de clase."
            elif turno == 1:
                estado = "Ausente"
                observacion = ""
            elif turno == 2:
                estado = "Falta Justificada"
                observacion = "Permiso familiar registrado."
            else:
                estado = "Presente"
                observacion = ""

            conn.execute(
                """
                INSERT INTO Asistencia (id_alumno, fecha, estado, observacion)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id_alumno, fecha) DO NOTHING
                """,
                (id_alumno, fecha.isoformat(), estado, observacion),
            )

        dias_registrados += 1


def cargar_notas_demo(conn, alumnos, cursos):
    # Dos alumnos tienen notas bajas en Matemática y Comunicación.
    # El tercer bimestre queda libre para registrar calificaciones en clase.
    for numero, id_alumno in alumnos.items():
        for posicion, (asignatura, id_curso) in enumerate(cursos.items()):
            for bimestre in (1, 2):
                nota = 12 + ((numero + posicion + bimestre) % 8)

                if numero in (6, 15) and asignatura in ("MATEMÁTICA", "COMUNICACIÓN"):
                    nota = 9 if bimestre == 1 else 10

                conn.execute(
                    """
                    INSERT INTO Calificaciones (id_alumno, id_curso, periodo, nota)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id_alumno, id_curso, periodo) DO NOTHING
                    """,
                    (id_alumno, id_curso, f"Bimestre {bimestre}", nota),
                )


def cargar_tareas_demo(conn, cursos, hoy):
    columnas = {
        fila["name"] for fila in conn.execute("PRAGMA table_info(Tareas)")
    }

    for asignatura, titulo, descripcion, dias in TAREAS_DEMO:
        id_curso = cursos[asignatura]

        existe = conn.execute(
            "SELECT 1 FROM Tareas WHERE id_curso = ? AND titulo = ?",
            (id_curso, titulo),
        ).fetchone()

        if existe:
            continue

        fecha_entrega = (hoy + timedelta(days=dias)).isoformat()
        datos = (id_curso, titulo, descripcion, fecha_entrega)

        if "periodo" in columnas:
            conn.execute(
                """
                INSERT INTO Tareas (
                    id_curso, titulo, descripcion, fecha_entrega, periodo
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (*datos, "Bimestre 2"),
            )
        else:
            conn.execute(
                """
                INSERT INTO Tareas (id_curso, titulo, descripcion, fecha_entrega)
                VALUES (?, ?, ?, ?)
                """,
                datos,
            )


def cargar_comunicados_demo(conn, id_admin):
    autor = "Dirección de demostración"
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

    for titulo, mensaje, categoria, destinatario in AVISOS_DEMO:
        existe = conn.execute(
            "SELECT 1 FROM Comunicados WHERE titulo = ? AND autor = ?",
            (titulo, autor),
        ).fetchone()

        if not existe:
            conn.execute(
                """
                INSERT INTO Comunicados (
                    titulo, mensaje, fecha, autor, categoria, destinatario, id_autor
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (titulo, mensaje, fecha, autor, categoria, destinatario, id_admin),
            )


def cargar_datos_prueba():
    if session.get("id_rol") != 1 or not session.get("id_usuario"):
        return redirect(url_for("index"))

    hoy = date.today()

    try:
        with closing(get_db_connection()) as conn, conn:
            # Si hay un conflicto, se revierte toda la carga.
            conn.execute("BEGIN IMMEDIATE")

            cursos = {}
            alumnos = {}

            for numero, (nombres, apellidos, materias) in enumerate(DOCENTES_DEMO, 1):
                id_docente = obtener_usuario_demo(conn, numero, nombres, apellidos, 2)

                for materia in materias:
                    cursos[materia] = obtener_curso_demo(conn, materia, id_docente)

            for numero, (nombres, apellidos) in enumerate(ALUMNOS_DEMO, 1):
                alumnos[numero] = obtener_usuario_demo(
                    conn, numero, nombres, apellidos, 3
                )

            cargar_asistencia_demo(conn, alumnos, hoy)
            cargar_notas_demo(conn, alumnos, cursos)
            cargar_tareas_demo(conn, cursos, hoy)
            cargar_comunicados_demo(conn, session["id_usuario"])

    except ValueError as error:
        flash(str(error))

    except sqlite3.OperationalError as error:
        if "locked" not in str(error).lower():
            raise
        flash("La base está ocupada. Espera unos segundos y vuelve a cargar la demo.")

    else:
        flash(
            f"Demo lista: {len(alumnos)} estudiantes, {len(DOCENTES_DEMO)} docentes "
            f"y {len(cursos)} cursos de {GRADO_DEMO}, sección {SECCION_DEMO}."
        )

    return redirect(url_for("dashboard"))


def limpiar_datos_prueba():
    if session.get("id_rol") != 1 or not session.get("id_usuario"):
        return redirect(url_for("index"))

    clave = request.form.get("clave_confirmacion", "").strip()

    if clave != "12345":
        flash("Contraseña de confirmación incorrecta. No se borró ningún dato.")
        return redirect(url_for("dashboard"))

    # «Vaciar Todo» también elimina los registros creados manualmente.
    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM EntregasTareas")
        conn.execute("DELETE FROM Tareas")
        conn.execute("DELETE FROM Calificaciones")
        conn.execute("DELETE FROM Asistencia")
        conn.execute("DELETE FROM Comunicados")
        conn.execute("DELETE FROM Cursos")
        conn.execute("DELETE FROM Usuarios WHERE id_rol IN (2, 3)")
        conn.execute(
            """
            DELETE FROM sqlite_sequence
            WHERE name IN (
                'Cursos', 'Asistencia', 'Calificaciones',
                'Comunicados', 'Tareas', 'EntregasTareas'
            )
            """
        )

    flash("Base de datos vaciada. Se conservaron las cuentas de administración.")
    return redirect(url_for("dashboard"))