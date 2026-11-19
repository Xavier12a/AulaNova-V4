"""Conexión e inicialización de la base de datos de AulaNova."""

import sqlite3


def get_db_connection():
    conn = sqlite3.connect('aulanova.db', timeout=15.0)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
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
            fecha TEXT NOT NULL,
            estado TEXT NOT NULL,
            observacion TEXT,
            FOREIGN KEY (id_alumno) REFERENCES Usuarios (id_usuario),
            UNIQUE(id_alumno, fecha)
        )
    ''')
    try:
        conn.execute('ALTER TABLE Asistencia ADD COLUMN observacion TEXT')
    except sqlite3.OperationalError:
        pass

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
            id_autor INTEGER
        )
    ''')
    for col_sql in [
        "ALTER TABLE Comunicados ADD COLUMN categoria TEXT DEFAULT 'General'",
        "ALTER TABLE Comunicados ADD COLUMN destinatario TEXT DEFAULT 'Toda la Comunidad'",
        "ALTER TABLE Comunicados ADD COLUMN id_autor INTEGER"
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
            FOREIGN KEY (id_tarea) REFERENCES Tareas (id_tarea),
            FOREIGN KEY (id_alumno) REFERENCES Usuarios (id_usuario),
            UNIQUE(id_tarea, id_alumno)
        )
    ''')
    
    roles_existentes = conn.execute('SELECT COUNT(*) FROM Roles').fetchone()[0]
    if roles_existentes == 0:
        conn.execute("INSERT INTO Roles (nombre_rol) VALUES ('Administrador')")
        conn.execute("INSERT INTO Roles (nombre_rol) VALUES ('Docente')")
        conn.execute("INSERT INTO Roles (nombre_rol) VALUES ('Estudiante')")
    
    admin_existente = conn.execute("SELECT COUNT(*) FROM Usuarios WHERE correo = 'admin@guadalupe.edu.pe'").fetchone()[0]
    if admin_existente == 0:
        conn.execute('''
            INSERT INTO Usuarios (nombres, apellidos, correo, password, dni, id_rol, estado)
            VALUES ('Xavier Antonio', 'Tamara Atanacio', 'admin@guadalupe.edu.pe', '123456', '00000000', 1, 1)
        ''')
        
    conn.commit()
    conn.close()
