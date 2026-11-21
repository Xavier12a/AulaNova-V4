"""Conexión e inicialización de la base de datos de AulaNova."""

import sqlite3


def get_db_connection():
    # Abre conexión a SQLite con modo WAL para mejorar concurrencia en lecturas/escrituras
    conn = sqlite3.connect('aulanova.db', timeout=15.0)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    # Crea tablas base, aplica migraciones incrementales y siembra roles y usuario administrador
    conn = get_db_connection()
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
            FOREIGN KEY (id_rol) REFERENCES Roles (id_rol)
        )
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
    cols_cursos = [row['name'] for row in conn.execute("PRAGMA table_info(Cursos)").fetchall()]
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
            SELECT id_curso, nombre_curso, grado, 'A', id_docente FROM Cursos_old
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
    cols_asist = [row['name'] for row in conn.execute("PRAGMA table_info(Asistencia)").fetchall()]
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
            INSERT INTO Asistencia (id_asistencia, id_alumno, id_curso, fecha, estado, observacion)
            SELECT id_asistencia, id_alumno, 0, fecha, estado, {obs_expr} FROM Asistencia_old
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
    for col_sql in [
        "ALTER TABLE Comunicados ADD COLUMN categoria TEXT DEFAULT 'General'",
        "ALTER TABLE Comunicados ADD COLUMN destinatario TEXT DEFAULT 'Toda la Comunidad'",
        "ALTER TABLE Comunicados ADD COLUMN id_autor INTEGER",
        "ALTER TABLE Comunicados ADD COLUMN fecha_evento TEXT",
        "ALTER TABLE Comunicados ADD COLUMN hora_evento TEXT",
        "ALTER TABLE Comunicados ADD COLUMN lugar_evento TEXT"
    ]:
        try:
            conn.execute(col_sql)
        except sqlite3.OperationalError:
            pass

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
    try:
        conn.execute('ALTER TABLE EntregasTareas ADD COLUMN comentario_docente TEXT')
    except sqlite3.OperationalError:
        pass

    # Inserta los roles base si la tabla está vacía
    roles_existentes = conn.execute('SELECT COUNT(*) FROM Roles').fetchone()[0]
    if roles_existentes == 0:
        conn.execute("INSERT INTO Roles (nombre_rol) VALUES ('Administrador')")
        conn.execute("INSERT INTO Roles (nombre_rol) VALUES ('Docente')")
        conn.execute("INSERT INTO Roles (nombre_rol) VALUES ('Estudiante')")

    # Crea la cuenta inicial de administrador si aún no existe
    admin_existente = conn.execute("SELECT COUNT(*) FROM Usuarios WHERE correo = 'admin@guadalupe.edu.pe'").fetchone()[0]
    if admin_existente == 0:
        conn.execute('''
            INSERT INTO Usuarios (nombres, apellidos, correo, password, dni, id_rol, estado)
            VALUES ('Xavier Antonio', 'Tamara Atanacio', 'admin@guadalupe.edu.pe', '123456', '00000000', 1, 1)
        ''')

    conn.commit()
    conn.close()