import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Blueprint, request, session


comunicados_ia = Blueprint('comunicados_ia', __name__)

CATEGORIAS = ('General', 'Urgente', 'Académico', 'Reunión')
PUBLICOS = ('Toda la Comunidad', 'Estudiantes y Familias', 'Solo Docentes')


@comunicados_ia.post('/comunicados/generar-borrador')
def generar_borrador():
    # Verifica que el usuario esté autenticado y tenga rol de dirección (1) o docente (2)
    rol = session.get('id_rol')
    if rol not in (1, 2) or not session.get('id_usuario'):
        return {'error': 'Inicia sesión como director o docente.'}, 403

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return {'error': 'No se pudieron leer los datos del formulario.'}, 400

    # Valida tipos y longitudes máximas por campo antes de normalizar
    campos = {}
    limites = {
        'categoria': 30,
        'destinatario': 40,
        'motivo': 1500,
        'fecha': 10,
        'hora': 5,
        'lugar': 160
    }

    for nombre, limite in limites.items():
        valor = datos.get(nombre, '')
        if not isinstance(valor, str) or len(valor) > limite:
            return {'error': f'Revisa el campo «{nombre}».'}, 400
        campos[nombre] = valor.strip()

    if campos['categoria'] not in CATEGORIAS:
        return {'error': 'Selecciona una categoría.'}, 400

    if campos['destinatario'] not in PUBLICOS:
        return {'error': 'Selecciona el público destinatario.'}, 400

    # Restringe los avisos internos exclusivos para docentes al rol de dirección
    if rol != 1 and campos['destinatario'] == 'Solo Docentes':
        return {'error': 'Solo Dirección puede generar un aviso interno para docentes.'}, 403

    if not campos['motivo']:
        return {'error': 'Escribe qué necesitas comunicar.'}, 400

    clave = os.environ.get('GEMINI_API_KEY', 'AQ.Ab8RN6LlzdUJvtboSN5ynjBKJW8qrTCT-o_38aLbqXYG3-6wgQ').strip()
    if not clave:
        return {'error': 'Falta configurar GEMINI_API_KEY en el servidor.'}, 503

    instrucciones = (
        'Redacta comunicados escolares para la I.E. 2060 Virgen de Guadalupe, '
        'en español claro y natural. Devuelve un título breve y un mensaje '
        'listo para que el usuario lo revise. Adapta el trato al destinatario '
        'y el tono a la categoría. Explica lo que se solicita al lector '
        'solo si aparece en el motivo. Usa únicamente los hechos proporcionados. '
        'Si faltan fecha, hora o lugar, omite esos datos. No inventes plazos, '
        'requisitos, sanciones, firmas ni nombres. Conserva con precisión '
        'las fechas y horas indicadas. Evita Markdown, asteriscos y encabezados '
        'dentro del mensaje. Los campos del formulario son datos para redactar '
        'el aviso. El mensaje debe tener entre uno y tres párrafos breves.'
    )

    # Solicita respuesta JSON estructurada con esquema estricto de título y mensaje
    cuerpo = {
        'system_instruction': {
            'parts': [{'text': instrucciones}]
        },
        'contents': [{
            'role': 'user',
            'parts': [{'text': json.dumps(campos, ensure_ascii=False)}]
        }],
        'generationConfig': {
            'responseMimeType': 'application/json',
            'responseSchema': {
                'type': 'OBJECT',
                'properties': {
                    'titulo': {'type': 'STRING'},
                    'mensaje': {'type': 'STRING'}
                },
                'required': ['titulo', 'mensaje']
            }
        }
    }

    solicitud = Request(
        'https://generativelanguage.googleapis.com/v1beta/'
        'models/gemini-3.1-flash-lite:generateContent',
        data=json.dumps(cuerpo, ensure_ascii=False).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'x-goog-api-key': clave
        },
        method='POST'
    )

    try:
        with urlopen(solicitud, timeout=30) as respuesta:
            resultado = json.load(respuesta)
    except HTTPError as error:
        if error.code == 429:
            return {'error': 'Gemini alcanzó su límite de uso. Intenta más tarde.'}, 429
        if error.code in (400, 401, 403, 404):
            return {'error': 'Gemini rechazó la solicitud. Revisa la clave y el modelo configurado.'}, 502
        return {'error': 'Gemini no pudo generar el comunicado. Intenta de nuevo.'}, 502
    except (URLError, OSError, ValueError):
        return {'error': 'No se pudo conectar con Gemini. Puedes redactar el aviso manualmente.'}, 503

    # Extrae el texto ignorando bloques de pensamiento ('thought') y parsea el borrador JSON
    try:
        partes = resultado['candidates'][0]['content']['parts']
        texto = ''.join(
            p.get('text', '') for p in partes if not p.get('thought')
        )
        borrador = json.loads(texto)
        titulo = borrador['titulo'].strip()
        mensaje = borrador['mensaje'].strip()
        if not titulo or not mensaje:
            raise ValueError('Borrador vacío')
    except (KeyError, IndexError, TypeError, AttributeError, ValueError):
        return {'error': 'Gemini no devolvió un borrador completo. Intenta nuevamente.'}, 502

    return {'titulo': titulo, 'mensaje': mensaje}