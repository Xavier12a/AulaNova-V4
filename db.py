"""Conexión e inicialización de la base de datos de AulaNova."""

import sqlite3


# Hash scrypt de la contraseña de la cuenta institucional.
HASH_ADMIN = (
    'scrypt:32768:8:1$jixvO1RpxSwCtrSa$'
    '98b6f9c20e874739e23aa839a4cc1f1ef12b7b87d81a875486172156d83773e2d'
    'ff7a6c9617146dba23a1ad6c9d90f4088d00e8d573cf0d15a31016dcba3b89c'
)


def get_db_connection():
    # Abre conexión a SQLite con modo WAL para mejorar concurrencia en lecturas/escrituras
    conn = sqlite3.connect('aulanova.db', timeout=15.0)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    # Crea tablas base, aplica migraciones incrementales y siembra roles y usuario administrador
    conn = get_db_connection()

    try:
        conn.execute('BEGIN IMMEDIATE')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS Roles (
                id_rol INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_rol TEXT NOT NULL
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS Usuarios (
                id_usuario INTEGER PRIMARY KEY AUTOINCREMENT,
                nombres TEXT NOT NULL,
                apellidos TEXT NOT NULL,
                correo TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                dni TEXT,
                grado TEXT,
                seccion TEXT,
                id_rol INTEGER,
                estado INTEGER DEFAULT 1,
                clave_temporal INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (id_rol) REFERENCES Roles (id_rol)
            )
        ''')

        # Las bases antiguas también necesitan la columna de clave temporal.
        cols_usuarios = [
            row['name'] for row in conn.execute('PRAGMA table_info(Usuarios)')
        ]
        if 'clave_temporal' not in cols_usuarios:
            conn.execute('''
                ALTER TABLE Usuarios
                ADD COLUMN clave_temporal INTEGER NOT NULL DEFAULT 0
            ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS Cursos (
                id_curso INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_curso TEXT NOT NULL,
                grado TEXT NOT NULL,
                seccion TEXT NOT NULL DEFAULT 'A',
                id_docente INTEGER,
                FOREIGN KEY (id_docente) REFERENCES Usuarios (id_usuario),
                UNIQUE(nombre_curso, grado, seccion)
            )
        ''')

        # Migra tablas antiguas de Cursos si aún no incluyen la columna seccion
        cols_cursos = [
            row['name'] for row in conn.execute('PRAGMA table_info(Cursos)')
        ]
        if 'seccion' not in cols_cursos:
            conn.execute('ALTER TABLE Cursos RENAME TO Cursos_old')
            conn.execute('''
                CREATE TABLE Cursos (
                    id_curso INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_curso TEXT NOT NULL,
                    grado TEXT NOT NULL,
                    seccion TEXT NOT NULL DEFAULT 'A',
                    id_docente INTEGER,
                    FOREIGN KEY (id_docente) REFERENCES Usuarios (id_usuario),
                    UNIQUE(nombre_curso, grado, seccion)
                )
            ''')
            conn.execute('''
                INSERT INTO Cursos (id_curso, nombre_curso, grado, seccion, id_docente)
                SELECT id_curso, nombre_curso, grado, 'A', id_docente
                FROM Cursos_old
            ''')
            conn.execute('DROP TABLE Cursos_old')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS Asistencia (
                id_asistencia INTEGER PRIMARY KEY AUTOINCREMENT,
                id_alumno INTEGER,
                id_curso INTEGER DEFAULT 0,
                fecha TEXT NOT NULL,
                estado TEXT NOT NULL,
                observacion TEXT,
                FOREIGN KEY (id_alumno) REFERENCES Usuarios (id_usuario),
                FOREIGN KEY (id_curso) REFERENCES Cursos (id_curso),
                UNIQUE(id_alumno, id_curso, fecha)
            )
        ''')

        # Migra Asistencia para soportar id_curso y observacion conservando registros previos
        cols_asist = [
            row['name'] for row in conn.execute('PRAGMA table_info(Asistencia)')
        ]
        if 'id_curso' not in cols_asist:
            obs_expr = 'observacion' if 'observacion' in cols_asist else 'NULL'
            conn.execute('ALTER TABLE Asistencia RENAME TO Asistencia_old')
            conn.execute('''
                CREATE TABLE Asistencia (
                    id_asistencia INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_alumno INTEGER,
                    id_curso INTEGER DEFAULT 0,
                    fecha TEXT NOT NULL,
                    estado TEXT NOT NULL,
                    observacion TEXT,
                    FOREIGN KEY (id_alumno) REFERENCES Usuarios (id_usuario),
                    FOREIGN KEY (id_curso) REFERENCES Cursos (id_curso),
                    UNIQUE(id_alumno, id_curso, fecha)
                )
            ''')
            conn.execute(f'''
                INSERT INTO Asistencia (
                    id_asistencia, id_alumno, id_curso, fecha, estado, observacion
                )
                SELECT id_asistencia, id_alumno, 0, fecha, estado, {obs_expr}
                FROM Asistencia_old
            ''')
            conn.execute('DROP TABLE Asistencia_old')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS Calificaciones (
                id_calificacion INTEGER PRIMARY KEY AUTOINCREMENT,
                id_alumno INTEGER,
                id_curso INTEGER,
                periodo TEXT NOT NULL,
                nota REAL,
                FOREIGN KEY (id_alumno) REFERENCES Usuarios (id_usuario),
                FOREIGN KEY (id_curso) REFERENCES Cursos (id_curso),
                UNIQUE(id_alumno, id_curso, periodo)
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS Comunicados (
                id_comunicado INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                mensaje TEXT NOT NULL,
                fecha TEXT NOT NULL,
                autor TEXT NOT NULL,
                categoria TEXT DEFAULT 'General',
                destinatario TEXT DEFAULT 'Toda la Comunidad',
                id_autor INTEGER,
                fecha_evento TEXT,
                hora_evento TEXT,
                lugar_evento TEXT
            )
        ''')

        # Añade columnas de metadata y evento si la tabla Comunicados ya existía
        cols_comunicados = {
            row['name'] for row in conn.execute('PRAGMA table_info(Comunicados)')
        }
        for columna, definicion in [
            ('categoria', "TEXT DEFAULT 'General'"),
            ('destinatario', "TEXT DEFAULT 'Toda la Comunidad'"),
            ('id_autor', 'INTEGER'),
            ('fecha_evento', 'TEXT'),
            ('hora_evento', 'TEXT'),
            ('lugar_evento', 'TEXT'),
        ]:
            if columna not in cols_comunicados:
                conn.execute(
                    f'ALTER TABLE Comunicados ADD COLUMN {columna} {definicion}'
                )

        conn.execute('''
            CREATE TABLE IF NOT EXISTS Tareas (
                id_tarea INTEGER PRIMARY KEY AUTOINCREMENT,
                id_curso INTEGER,
                titulo TEXT NOT NULL,
                descripcion TEXT NOT NULL,
                fecha_entrega TEXT NOT NULL,
                archivo_adjunto TEXT,
                FOREIGN KEY (id_curso) REFERENCES Cursos (id_curso)
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS EntregasTareas (
                id_entrega INTEGER PRIMARY KEY AUTOINCREMENT,
                id_tarea INTEGER,
                id_alumno INTEGER,
                archivo_alumno TEXT NOT NULL,
                fecha_entrega TEXT NOT NULL,
                nota_tarea REAL,
                comentario_docente TEXT,
                FOREIGN KEY (id_tarea) REFERENCES Tareas (id_tarea),
                FOREIGN KEY (id_alumno) REFERENCES Usuarios (id_usuario),
                UNIQUE(id_tarea, id_alumno)
            )
        ''')

        cols_entregas = {
            row['name'] for row in conn.execute('PRAGMA table_info(EntregasTareas)')
        }
        if 'comentario_docente' not in cols_entregas:
            conn.execute('ALTER TABLE EntregasTareas ADD COLUMN comentario_docente TEXT')

        # Inserta los roles base si la tabla está vacía
        roles_existentes = conn.execute('SELECT COUNT(*) FROM Roles').fetchone()[0]
        if roles_existentes == 0:
            conn.execute("INSERT INTO Roles (nombre_rol) VALUES ('Administrador')")
            conn.execute("INSERT INTO Roles (nombre_rol) VALUES ('Docente')")
            conn.execute("INSERT INTO Roles (nombre_rol) VALUES ('Estudiante')")

        # Crea la cuenta inicial de administrador si aún no existe.
        # Si ya existe, conserva su ID y reemplaza la contraseña en texto por su hash.
        conn.execute('''
            INSERT INTO Usuarios (
                nombres, apellidos, correo, password, dni, id_rol, estado, clave_temporal
            )
            VALUES (
                'Administrador', 'AulaNova', 'admin@guadalupe.edu.pe',
                ?, '00000000', 1, 1, 0
            )
            ON CONFLICT(correo) DO UPDATE SET
                nombres = excluded.nombres,
                apellidos = excluded.apellidos,
                password = CASE
                    WHEN Usuarios.password LIKE 'scrypt:%'
                      OR Usuarios.password LIKE 'pbkdf2:%'
                    THEN Usuarios.password
                    ELSE excluded.password
                END,
                clave_temporal = 0
            WHERE Usuarios.id_rol = 1
        ''', (HASH_ADMIN,))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()