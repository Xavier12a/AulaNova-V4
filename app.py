"""Inicio, gestión de contraseñas y consulta de la base de datos de AulaNova."""

import hmac
import secrets
from contextlib import closing

from flask import (
    abort, flash, redirect, render_template, render_template_string,
    request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash

from academico import app
from db import get_db_connection


@app.template_filter("nota_literal")
def filtro_nota_literal(valor):
    """Convierte una calificación vigesimal (0-20) a la escala literal MINEDU (AD, A, B, C)."""
    if valor is None or isinstance(valor, bool):
        return ""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return ""

    if numero >= 18.0:
        return "AD"
    if numero >= 14.0:
        return "A"
    if numero >= 11.0:
        return "B"
    return "C"


@app.template_filter("con_literal")
def filtro_con_literal(valor, decimales=1):
    """Formatea una nota numérica junto a su equivalencia literal MINEDU (ej. '18.5 (AD)')."""
    if valor is None or isinstance(valor, bool):
        return "-"
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor)

    literal = filtro_nota_literal(numero)
    if decimales is None:
        texto_num = f"{numero:g}"
    else:
        texto_num = f"{numero:.{int(decimales)}f}"
    return f"{texto_num} ({literal})"


def preparar_cuentas():
    # Asegura columnas de control de sesiones/claves, llave secreta persistente y trigger docente
    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")

        columnas = {
            fila["name"] for fila in conn.execute("PRAGMA table_info(Usuarios)")
        }

        if "version_clave" not in columnas:
            conn.execute("""
                ALTER TABLE Usuarios
                ADD COLUMN version_clave INTEGER NOT NULL DEFAULT 0
            """)

        if "clave_temporal" not in columnas:
            conn.execute("""
                ALTER TABLE Usuarios
                ADD COLUMN clave_temporal INTEGER NOT NULL DEFAULT 0
            """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS ConfiguracionAcceso (
                nombre TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO ConfiguracionAcceso (nombre, valor)
            VALUES ('firma_sesion', ?)
        """, (secrets.token_hex(32),))

        app.secret_key = conn.execute("""
            SELECT valor FROM ConfiguracionAcceso WHERE nombre = 'firma_sesion'
        """).fetchone()["valor"]

        # Si un docente aún usa su DNI como contraseña y se actualiza su DNI, sincroniza clave e invalida sesiones viejas
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS sincronizar_dni_docente
            AFTER UPDATE OF dni ON Usuarios
            WHEN NEW.id_rol = 2
                 AND OLD.dni IS NOT NEW.dni
                 AND OLD.password = OLD.dni
            BEGIN
                UPDATE Usuarios
                SET password = NEW.dni,
                    version_clave = version_clave + 1
                WHERE id_usuario = NEW.id_usuario;
            END
        """)


preparar_cuentas()


def clave_valida(guardada, ingresada):
    # Soporta hashes Werkzeug (scrypt/pbkdf2) y comparación segura para claves legadas en texto plano
    if not guardada or not ingresada:
        return False

    if guardada.startswith(("scrypt:", "pbkdf2:")):
        return check_password_hash(guardada, ingresada)

    return hmac.compare_digest(
        guardada.encode("utf-8"), ingresada.encode("utf-8")
    )


def requiere_cambio(usuario):
    return bool(usuario["clave_temporal"])


def token_formulario():
    # Genera o reutiliza un token CSRF por sesión para formularios sensibles
    if "token_formulario" not in session:
        session["token_formulario"] = secrets.token_urlsafe(32)
    return session["token_formulario"]


def verificar_formulario():
    recibido = request.form.get("token", "")
    esperado = session.get("token_formulario", "")

    if not esperado or not hmac.compare_digest(
        recibido.encode("utf-8"), esperado.encode("utf-8")
    ):
        abort(400, "El formulario caducó. Vuelve a abrir la página.")


def iniciar_sesion():
    identificador = request.form.get("correo", "").strip()
    clave = request.form.get("password", "")

    with closing(get_db_connection()) as conn:
        usuario = conn.execute("""
            SELECT * FROM Usuarios WHERE correo = ? OR dni = ?
        """, (identificador, identificador)).fetchone()

    if not usuario or not clave_valida(usuario["password"], clave):
        return render_template(
            "login.html", error="Correo o DNI / Contraseña incorrectos."
        )

    session.clear()
    session["id_usuario"] = usuario["id_usuario"]
    session["id_rol"] = usuario["id_rol"]
    session["version_clave"] = usuario["version_clave"]

    if requiere_cambio(usuario):
        return redirect(url_for("cambiar_clave"))

    return redirect(url_for("index"))


app.view_functions["login"] = iniciar_sesion


@app.before_request
def comprobar_sesion():
    # Valida en cada petición que la sesión siga vigente y que no haya cambio de contraseña pendiente
    if request.endpoint in {"static", "login", "logout"}:
        return None

    id_usuario = session.get("id_usuario")
    if id_usuario is None:
        return None

    with closing(get_db_connection()) as conn:
        usuario = conn.execute("""
            SELECT id_rol, dni, password, version_clave, clave_temporal
            FROM Usuarios WHERE id_usuario = ?
        """, (id_usuario,)).fetchone()

    if (
        not usuario
        or session.get("version_clave") != usuario["version_clave"]
        or session.get("id_rol") != usuario["id_rol"]
    ):
        session.clear()
        return redirect(url_for("index"))

    if requiere_cambio(usuario) and request.endpoint != "cambiar_clave":
        return redirect(url_for("cambiar_clave"))

    return None


# Tablas y columnas que puede mostrar el director en la presentación.
# La primera columna de cada tabla es su identificador y define el orden.
TABLAS_VISIBLES = {
    "Usuarios": (
        "id_usuario", "nombres", "apellidos", "id_rol", "grado", "seccion", "estado"
    ),
    "Roles": (
        "id_rol", "nombre_rol"
    ),
    "Cursos": (
        "id_curso", "nombre_curso", "grado", "seccion", "id_docente"
    ),
    "Tareas": (
        "id_tarea", "id_curso", "titulo", "periodo", "fecha_entrega"
    ),
    "EntregasTareas": (
        "id_entrega", "id_tarea", "id_alumno", "fecha_entrega", "nota_tarea"
    ),
    "Asistencia": (
        "id_asistencia", "id_alumno", "fecha", "estado"
    ),
    "Calificaciones": (
        "id_calificacion", "id_alumno", "id_curso", "periodo", "nota", "es_manual"
    ),
    "Comunicados": (
        "id_comunicado", "titulo", "fecha", "categoria", "destinatario", "id_autor"
    ),
}


@app.get("/admin/base-de-datos")
def base_datos():
    # Visor paginado de solo lectura exclusivo para el rol administrador (id_rol == 1)
    if session.get("id_usuario") is None:
        return redirect(url_for("index"))
    if session.get("id_rol") != 1:
        abort(403)

    tabla = request.args.get("tabla", "Usuarios")
    if tabla not in TABLAS_VISIBLES:
        abort(404)

    columnas = TABLAS_VISIBLES[tabla]
    pagina = request.args.get("pagina", default=1, type=int)
    por_pagina = 25

    with closing(get_db_connection()) as conn:
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")

        usuario = conn.execute("""
            SELECT nombres, apellidos FROM Usuarios WHERE id_usuario = ?
        """, (session["id_usuario"],)).fetchone()

        # Los nombres de tabla y columnas proceden de la whitelist TABLAS_VISIBLES
        total = conn.execute(f'SELECT COUNT(*) FROM "{tabla}"').fetchone()[0]
        paginas = max(1, (total + por_pagina - 1) // por_pagina)
        pagina = min(max(1, pagina), paginas)
        desplazamiento = (pagina - 1) * por_pagina

        campos = ", ".join(f'"{columna}"' for columna in columnas)
        filas = conn.execute(f"""
            SELECT {campos}
            FROM "{tabla}"
            ORDER BY "{columnas[0]}" DESC
            LIMIT ? OFFSET ?
        """, (por_pagina, desplazamiento)).fetchall()

    return render_template(
        "Admin/base_datos.html",
        usuario=usuario,
        tablas=TABLAS_VISIBLES,
        tabla=tabla,
        columnas=columnas,
        filas=filas,
        total=total,
        pagina=pagina,
        paginas=paginas,
    )


PANTALLA_CLAVE = """
{% extends "layout.html" %}
{% block title %}{{ titulo }} - AulaNova{% endblock %}
{% block header_title %}{{ titulo }}{% endblock %}
{% block extra_style %}
<style>
    .clave-panel {
        max-width: 520px;
        background: white;
        color: #17283b;
        border: 1px solid #dce4ed;
        border-radius: 12px;
        padding: 24px;
    }
    .clave-panel h2 { margin: 0 0 12px; }
    .clave-panel p { line-height: 1.5; margin: 10px 0 18px; }
    .clave-panel label { display: block; margin: 12px 0 5px; }
    .clave-panel input {
        box-sizing: border-box;
        width: 100%;
        padding: 10px;
        border: 1px solid #becbd9;
        border-radius: 6px;
    }
    .clave-panel button {
        margin: 15px 12px 0 0;
        border: 0;
        padding: 10px 16px;
        background: #08689b;
        color: white;
        border-radius: 6px;
        cursor: pointer;
    }
    .clave-error { color: #a52820; }
    .clave-generada {
        display: inline-block;
        padding: 10px 14px;
        background: #edf4fa;
        font-size: 18px;
        user-select: all;
    }
</style>
{% endblock %}

{% block content %}
<section class="clave-panel">
    <h2>{{ titulo }}</h2>

    {% if error %}
        <p class="clave-error" role="alert">{{ error }}</p>
    {% endif %}

    {% if modo == 'personal' %}
        {% if obligatorio %}
            <p>Estás usando una contraseña temporal.
               Elige una contraseña personal para continuar.</p>
        {% endif %}

        <form method="post">
            <input type="hidden" name="token" value="{{ token }}">

            <label for="actual">Contraseña actual</label>
            <input id="actual" name="actual" type="password"
                   autocomplete="current-password" required>

            <label for="nueva">Nueva contraseña</label>
            <input id="nueva" name="nueva" type="password"
                   minlength="8" maxlength="128" autocomplete="new-password" required>
            <small>Usa entre 8 y 128 caracteres.</small>

            <label for="repetida">Repetir nueva contraseña</label>
            <input id="repetida" name="repetida" type="password"
                   minlength="8" maxlength="128" autocomplete="new-password" required>

            <div>
                <button type="submit">Guardar contraseña</button>
                {% if not obligatorio %}
                    <a href="{{ url_for('index') }}">Cancelar</a>
                {% endif %}
            </div>
        </form>

    {% elif modo == 'confirmar' %}
        <p>Se generará una contraseña temporal para
           <strong>{{ docente.nombres }} {{ docente.apellidos }}</strong>,
           DNI {{ docente.dni }}. Tendrá que elegir su propia contraseña
           al volver a ingresar.</p>

        <form method="post">
            <input type="hidden" name="token" value="{{ token }}">
            <input type="hidden" name="version" value="{{ docente.version_clave }}">
            <button type="submit">Generar contraseña temporal</button>
            <a href="{{ url_for('gestionar_docentes') }}">Cancelar</a>
        </form>

    {% elif modo == 'resultado' %}
        <p>Entrega esta contraseña temporal a
           <strong>{{ docente.nombres }} {{ docente.apellidos }}</strong>.
           Cópiala antes de salir de esta página.</p>
        <code class="clave-generada">{{ temporal }}</code>
        <p><a href="{{ url_for('gestionar_docentes') }}">Volver a docentes</a></p>
    {% endif %}
</section>
{% endblock %}
"""


@app.route("/perfil/cambiar-contrasena", methods=["GET", "POST"])
def cambiar_clave():
    id_usuario = session.get("id_usuario")
    if id_usuario is None:
        return redirect(url_for("index"))

    error = None

    with closing(get_db_connection()) as conn, conn:
        usuario = conn.execute("""
            SELECT * FROM Usuarios WHERE id_usuario = ?
        """, (id_usuario,)).fetchone()

        if not usuario:
            session.clear()
            return redirect(url_for("index"))

        if request.method == "POST":
            verificar_formulario()
            actual = request.form.get("actual", "")
            nueva = request.form.get("nueva", "")
            repetida = request.form.get("repetida", "")

            if not clave_valida(usuario["password"], actual):
                error = "La contraseña actual es incorrecta."
            elif nueva != repetida:
                error = "Las dos contraseñas nuevas no coinciden."
            elif not 8 <= len(nueva) <= 128 or not nueva.strip():
                error = "Escribe una contraseña de entre 8 y 128 caracteres."
            elif nueva == usuario["dni"]:
                error = "Elige una contraseña distinta de tu DNI."
            elif nueva == actual:
                error = "Elige una contraseña distinta de la actual."
            else:
                # Actualización condicional por versión y clave para evitar condiciones de carrera
                cambio = conn.execute("""
                    UPDATE Usuarios
                    SET password = ?, clave_temporal = 0,
                        version_clave = version_clave + 1
                    WHERE id_usuario = ? AND version_clave = ? AND password = ?
                """, (
                    generate_password_hash(nueva), id_usuario,
                    usuario["version_clave"], usuario["password"]
                ))

                if cambio.rowcount != 1:
                    session.clear()
                    return redirect(url_for("index"))

                session["version_clave"] = usuario["version_clave"] + 1
                session.pop("token_formulario", None)
                flash("Tu contraseña se actualizó correctamente.")
                return redirect(url_for("index"))

    return render_template_string(
        PANTALLA_CLAVE, titulo="Cambiar contraseña", modo="personal",
        usuario=usuario, obligatorio=requiere_cambio(usuario), error=error,
        token=token_formulario()
    )


@app.route("/docentes/<int:id_docente>/restablecer-clave", methods=["GET", "POST"])
def restablecer_clave(id_docente):
    # Permite al administrador emitir una contraseña temporal que fuerza el cambio en el próximo login
    if session.get("id_rol") != 1:
        abort(403)

    with closing(get_db_connection()) as conn, conn:
        docente = conn.execute("""
            SELECT id_usuario, nombres, apellidos, dni, version_clave
            FROM Usuarios WHERE id_usuario = ? AND id_rol = 2
        """, (id_docente,)).fetchone()

        if not docente:
            abort(404)

        admin = conn.execute("""
            SELECT nombres, apellidos FROM Usuarios WHERE id_usuario = ?
        """, (session["id_usuario"],)).fetchone()

        if request.method == "POST":
            verificar_formulario()
            version = request.form.get("version", type=int)
            temporal = secrets.token_urlsafe(12)

            cambio = conn.execute("""
                UPDATE Usuarios
                SET password = ?, clave_temporal = 1,
                    version_clave = version_clave + 1
                WHERE id_usuario = ? AND id_rol = 2 AND version_clave = ?
            """, (generate_password_hash(temporal), id_docente, version))

            if cambio.rowcount != 1:
                flash("La clave de este docente ya cambió. Revisa su cuenta antes de continuar.")
                return redirect(url_for("gestionar_docentes"))

            return render_template_string(
                PANTALLA_CLAVE, titulo="Contraseña temporal", modo="resultado",
                usuario=admin, docente=docente, temporal=temporal
            )

    return render_template_string(
        PANTALLA_CLAVE, titulo="Restablecer contraseña", modo="confirmar",
        usuario=admin, docente=docente, token=token_formulario()
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)