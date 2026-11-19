"""Carga y limpieza de los datos ficticios de demostración de AulaNova."""

import random
from contextlib import closing
from datetime import datetime, timedelta

from flask import flash, redirect, request, session, url_for

from db import get_db_connection


GRADO_DEMO = '3ro de Primaria'
SECCION_DEMO = 'E'

# Identidades inventadas para la demostración.
# Los códigos de ocho dígitos permiten probar el formulario de ingreso.
DOCENTES_DEMO = (
    ('Docente 01', 'Demostración', '98000001'),
    ('Docente 02', 'Demostración', '98000002'),
    ('Docente 03', 'Demostración', '98000003'),
    ('Docente 04', 'Demostración', '98000004'),
)

CURSOS_POR_DOCENTE = (
    ('MATEMÁTICA', 'COMUNICACIÓN', 'PERSONAL SOCIAL', 'CIENCIA Y TECNOLOGÍA'),
    ('ARTE Y CULTURA',),
    ('EDUCACIÓN FÍSICA',),
    ('EDUCACIÓN RELIGIOSA', 'INGLÉS'),
)


def registrar_rutas_demo(app):
    app.add_url_rule(
        '/admin/cargar-datos-prueba',
        view_func=cargar_datos_prueba,
        methods=['POST']
    )
    app.add_url_rule(
        '/admin/limpiar-datos-prueba',
        view_func=limpiar_datos_prueba,
        methods=['POST']
    )


def obtener_usuario_demo(conn, nombres, apellidos, codigo, rol,
                        grado=None, seccion=None):
    correo = f'{codigo}@example.invalid'

    # Al repetir la carga se reutiliza la cuenta ficticia.
    # Si el código ya pertenece a otra persona, se cancela la operación.
    filas = conn.execute(
        '''
        SELECT id_usuario, nombres, apellidos, dni, correo, id_rol, grado, seccion
        FROM Usuarios
        WHERE dni = ? OR correo = ?
        ''',
        (codigo, correo)
    ).fetchall()

    if filas:
        usuario = filas[0]
        misma_cuenta = (
            len(filas) == 1
            and usuario['dni'] == codigo
            and usuario['correo'] == correo
            and usuario['nombres'] == nombres
            and usuario['apellidos'] == apellidos
            and usuario['id_rol'] == rol
            and usuario['grado'] == grado
            and usuario['seccion'] == seccion
        )

        if not misma_cuenta:
            raise ValueError(
                f'El código de prueba {codigo} ya está en uso. '
                'Se canceló la carga para proteger los registros existentes.'
            )

        return usuario['id_usuario']

    cursor = conn.execute(
        '''
        INSERT INTO Usuarios (
            nombres, apellidos, correo, password, dni,
            grado, seccion, id_rol, estado
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''',
        (nombres, apellidos, correo, codigo, codigo, grado, seccion, rol)
    )
    return cursor.lastrowid


def cargar_datos_prueba():
    if session.get('id_rol') != 1 or not session.get('id_usuario'):
        return redirect(url_for('index'))

    hoy = datetime.now()

    try:
        with closing(get_db_connection()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')

            # Cuatro docentes ficticios y ocho cursos para 3ro de Primaria E.
            cursos = {}

            for docente, asignaturas in zip(DOCENTES_DEMO, CURSOS_POR_DOCENTE):
                nombres, apellidos, codigo = docente

                id_docente = obtener_usuario_demo(
                    conn, nombres, apellidos, codigo, rol=2
                )

                for asignatura in asignaturas:
                    conn.execute(
                        '''
                        INSERT INTO Cursos (nombre_curso, grado, seccion, id_docente)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(nombre_curso, grado, seccion) DO NOTHING
                        ''',
                        (asignatura, GRADO_DEMO, SECCION_DEMO, id_docente)
                    )

                    curso = conn.execute(
                        '''
                        SELECT id_curso FROM Cursos
                        WHERE nombre_curso = ? AND grado = ? AND seccion = ?
                        ''',
                        (asignatura, GRADO_DEMO, SECCION_DEMO)
                    ).fetchone()

                    cursos[asignatura] = curso['id_curso']

            # Estudiante 01 a Estudiante 22, con códigos 99000001 a 99000022.
            alumnos = {}

            for numero in range(1, 23):
                codigo = f'99{numero:06d}'
                alumnos[numero] = obtener_usuario_demo(
                    conn,
                    nombres=f'Estudiante {numero:02d}',
                    apellidos='Demostración',
                    codigo=codigo,
                    rol=3,
                    grado=GRADO_DEMO,
                    seccion=SECCION_DEMO
                )

            # Los cinco días anteriores tienen asistencia simulada.
            # El día actual queda libre para registrar asistencia en la exposición.
            estados = (
                'Presente', 'Presente', 'Presente', 'Presente',
                'Tardanza', 'Ausente', 'Falta Justificada'
            )

            for dias_atras in range(1, 6):
                fecha = (hoy - timedelta(days=dias_atras)).strftime('%Y-%m-%d')

                for id_alumno in alumnos.values():
                    estado = random.choice(estados)
                    conn.execute(
                        '''
                        INSERT INTO Asistencia (
                            id_alumno, fecha, estado, observacion
                        )
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(id_alumno, fecha) DO NOTHING
                        ''',
                        (id_alumno, fecha, estado, 'Registro de demostración.')
                    )

            # Dos alumnos ficticios tienen notas bajas para probar la alerta.
            # El tercer bimestre queda libre para registrar notas en vivo.
            for numero, id_alumno in alumnos.items():
                for asignatura, id_curso in cursos.items():
                    en_riesgo = (
                        numero in (6, 15)
                        and asignatura in ('MATEMÁTICA', 'COMUNICACIÓN')
                    )
                    minimo, maximo = (9.5, 10.8) if en_riesgo else (12.5, 19.5)

                    for periodo in ('Bimestre 1', 'Bimestre 2'):
                        nota = round(random.uniform(minimo, maximo), 1)

                        conn.execute(
                            '''
                            INSERT INTO Calificaciones (
                                id_alumno, id_curso, periodo, nota
                            )
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(id_alumno, id_curso, periodo) DO NOTHING
                            ''',
                            (id_alumno, id_curso, periodo, nota)
                        )

            cargar_tareas_demo(conn, cursos, hoy)
            cargar_comunicados_demo(conn, session['id_usuario'], hoy)

    except ValueError as error:
        flash(str(error))
        return redirect(url_for('dashboard'))

    flash('Demo cargada: 22 alumnos ficticios, 4 docentes y 8 cursos de Primaria E.')
    return redirect(url_for('dashboard'))


def cargar_tareas_demo(conn, cursos, hoy):
    tareas = (
        (
            'MATEMÁTICA',
            'Resolución de problemas de multiplicación',
            'Resolver los ejercicios de las páginas 42 y 43 del cuaderno de Matemática.'
        ),
        (
            'COMUNICACIÓN',
            'Lectura comprensiva y resumen de una fábula',
            'Leer la fábula asignada y responder las cinco preguntas de comprensión.'
        ),
        (
            'CIENCIA Y TECNOLOGÍA',
            'Maqueta del sistema solar',
            'Elaborar una maqueta con materiales reciclados e identificar los planetas.'
        ),
    )

    fecha_limite = (hoy + timedelta(days=5)).strftime('%Y-%m-%d')
    columnas = {
        fila['name'] for fila in conn.execute('PRAGMA table_info(Tareas)')
    }

    for asignatura, titulo, descripcion in tareas:
        id_curso = cursos[asignatura]

        existe = conn.execute(
            'SELECT 1 FROM Tareas WHERE id_curso = ? AND titulo = ?',
            (id_curso, titulo)
        ).fetchone()

        if existe:
            continue

        if 'periodo' in columnas:
            conn.execute(
                '''
                INSERT INTO Tareas (
                    id_curso, titulo, descripcion, fecha_entrega, periodo
                )
                VALUES (?, ?, ?, ?, ?)
                ''',
                (id_curso, titulo, descripcion, fecha_limite, 'Bimestre 2')
            )
        else:
            conn.execute(
                '''
                INSERT INTO Tareas (id_curso, titulo, descripcion, fecha_entrega)
                VALUES (?, ?, ?, ?)
                ''',
                (id_curso, titulo, descripcion, fecha_limite)
            )


def cargar_comunicados_demo(conn, id_admin, hoy):
    if conn.execute('SELECT 1 FROM Comunicados LIMIT 1').fetchone():
        return

    avisos = (
        (
            'Cierre de registro de notas del segundo bimestre',
            'Se solicita a los docentes revisar las calificaciones '
            'del segundo bimestre antes del cierre de registro.',
            'Urgente',
            'Solo Docentes'
        ),
        (
            'Reunión del comité de aula de 3ro de Primaria E',
            'Se invita a las familias del aula de demostración a una reunión '
            'de coordinación con su docente titular.',
            'Reunión',
            'Estudiantes y Familias'
        ),
        (
            'Feria escolar de Ciencia y Matemática',
            'La comunidad educativa está invitada a la exposición '
            'de proyectos escolares de Primaria.',
            'Académico',
            'Toda la Comunidad'
        ),
    )

    fecha = hoy.strftime('%Y-%m-%d %H:%M')

    for titulo, mensaje, categoria, destinatario in avisos:
        conn.execute(
            '''
            INSERT INTO Comunicados (
                titulo, mensaje, fecha, autor, categoria, destinatario, id_autor
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                titulo, mensaje, fecha, 'Dirección de demostración',
                categoria, destinatario, id_admin
            )
        )


def limpiar_datos_prueba():
    if session.get('id_rol') != 1:
        return redirect(url_for('index'))

    clave_confirmacion = request.form.get('clave_confirmacion', '').strip()

    if clave_confirmacion != '12345':
        flash('Contraseña de confirmación incorrecta. No se borró ningún dato.')
        return redirect(url_for('dashboard'))

    # Esta acción corresponde al botón «Vaciar Todo» del panel administrativo.
    with closing(get_db_connection()) as conn, conn:
        conn.execute('DELETE FROM EntregasTareas')
        conn.execute('DELETE FROM Tareas')
        conn.execute('DELETE FROM Calificaciones')
        conn.execute('DELETE FROM Asistencia')
        conn.execute('DELETE FROM Comunicados')
        conn.execute('DELETE FROM Cursos')
        conn.execute('DELETE FROM Usuarios WHERE id_rol IN (2, 3)')
        conn.execute(
            '''
            DELETE FROM sqlite_sequence
            WHERE name IN (
                'Cursos', 'Asistencia', 'Calificaciones',
                'Comunicados', 'Tareas', 'EntregasTareas'
            )
            '''
        )

    flash('Base de datos vaciada. Se conservaron las cuentas de administración.')
    return redirect(url_for('dashboard'))