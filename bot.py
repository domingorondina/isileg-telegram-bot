"""
Bot de Telegram para ISILeg Web (Senado de Santa Fe)
Permite buscar leyes por número o temática, descargar PDFs y explorar normas vinculadas.
"""

import os
import io
import sys
import asyncio
import html
import logging
from typing import Optional
from dotenv import load_dotenv

# Asegurar codificación UTF-8 en la salida de consola de Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from isileg_api import ISILegAPI

# Cargar variables de entorno desde .env
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "8080"))

# Configurar logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

api = ISILegAPI()

PAGE_SIZE = 5

async def handle_http_health_check(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Responde con 200 OK y permite /test para verificar conectividad con ISILeg desde Render."""
    try:
        first_line = await reader.readline()
        path = "/"
        if first_line:
            parts = first_line.decode('utf-8', errors='ignore').split()
            if len(parts) > 1:
                path = parts[1]
                
        while True:
            line = await reader.readline()
            if line == b'\r\n' or line == b'\n' or not line:
                break

        if path.startswith("/test"):
            # Probar conexión real con ISILeg desde la IP de Render
            try:
                test_res = await api.search_leyes(numero_ley="14207", page=0, page_size=1)
                body = f"ISILeg OK: Found {test_res.get('cant')} items".encode('utf-8')
                resp_code = b"200 OK"
            except Exception as e:
                body = f"ISILeg ERROR: {type(e).__name__}: {str(e)}".encode('utf-8')
                resp_code = b"500 Internal Error"
        else:
            body = b"OK"
            resp_code = b"200 OK"

        response = (
            b"HTTP/1.1 " + resp_code + b"\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Length: " + str(len(body)).encode('ascii') + b"\r\n"
            b"Connection: close\r\n\r\n" + body
        )
        writer.write(response)
        await writer.drain()
    except Exception as e:
        logger.debug(f"Error en health check: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

async def start_http_server():
    try:
        server = await asyncio.start_server(handle_http_health_check, "0.0.0.0", PORT)
        logger.info(f"Servidor HTTP de Health Check escuchando en el puerto {PORT}")
        async with server:
            await server.serve_forever()
    except Exception as e:
        logger.error(f"No se pudo iniciar el servidor HTTP en el puerto {PORT}: {e}")

async def post_init(application):
    """Hook que se ejecuta tras iniciar la aplicación para arrancar el servidor HTTP en Render."""
    asyncio.create_task(start_http_server())

def format_estado_badge(estado: Optional[str]) -> str:
    if not estado:
        return "⚪ Estado no especificado"
    est = estado.lower()
    if "vigente" in est and "no" not in est:
        return f"🟢 <b>{estado}</b>"
    elif "derogada" in est or "abrogada" in est:
        return f"🔴 <b>{estado}</b>"
    else:
        return f"🟡 <b>{estado}</b>"

def build_ley_card(detail: dict) -> str:
    texto = detail.get("texto") or f"Ley Nº {detail.get('numeroLey')}"
    asunto = detail.get("asunto") or "Sin asunto registrado"
    estado = detail.get("tipoEstadoLey") or detail.get("estado") or "Vigente"
    fecha_sancion = detail.get("fechaSancion") or "No disponible"
    fecha_prom = detail.get("fechaPromulgacion") or "No disponible"
    fecha_pub = detail.get("fechaPublicacion") or "No disponible"
    nro_bo = detail.get("numeroBo") or "-"
    nro_exp = detail.get("numeroExpediente") or "-"

    badge = format_estado_badge(estado)

    card_text = (
        f"⚖️ <b>{html.escape(texto)}</b>\n\n"
        f"<b>Estado:</b> {badge}\n"
        f"📅 <b>Sanción:</b> {html.escape(str(fecha_sancion))} | <b>Promulgación:</b> {html.escape(str(fecha_prom))}\n"
        f"📰 <b>Boletín Oficial:</b> Nº {html.escape(str(nro_bo))} ({html.escape(str(fecha_pub))})\n"
        f"📁 <b>Expediente Origen:</b> {html.escape(str(nro_exp))}\n\n"
        f"📝 <b>Asunto / Sumario:</b>\n<i>{html.escape(asunto)}</i>"
    )
    return card_text

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🏛️ <b>Bienvenido al Bot de Consulta de Leyes de Santa Fe</b>\n"
        "<i>Conectado oficialmente a ISILeg Web (Senado de Santa Fe)</i>\n\n"
        "🔍 <b>¿Cómo usar el bot?</b>\n\n"
        "1️⃣ <b>Búsqueda directa por Número de Ley:</b>\n"
        "   Simplemente escribe el número (ej: <code>12510</code> o <code>14477</code>) o usa <code>/ley 12510</code>.\n\n"
        "2️⃣ <b>Búsqueda por Tema / Palabras clave:</b>\n"
        "   Escribe lo que buscas (ej: <code>salud</code>, <code>seguridad deportiva</code>, <code>presupuesto</code>) o usa <code>/buscar ambiente</code>.\n\n"
        "📥 Podrás previsualizar la norma, descargar los <b>PDFs originales, actualizados y fichas técnicas</b>, y navegar por sus <b>normas relacionadas y modificatorias</b> con botones interactivos."
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_command(update, context)

async def ley_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Por favor indica el número de ley. Ejemplo: <code>/ley 12510</code>",
            parse_mode="HTML"
        )
        return
    numero = context.args[0]
    await handle_search_by_number(update, context, numero)

async def buscar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ Por favor indica el texto a buscar. Ejemplo: <code>/buscar salud publica</code>",
            parse_mode="HTML"
        )
        return
    query = " ".join(context.args)
    await handle_search_by_topic(update, context, query, page=0)

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    # Si es puramente numérico -> búsqueda por número de ley
    if text.isdigit():
        await handle_search_by_number(update, context, text)
    else:
        # Búsqueda temática por texto
        await handle_search_by_topic(update, context, text, page=0)

async def handle_search_by_number(update: Update, context: ContextTypes.DEFAULT_TYPE, numero: str):
    msg = await update.message.reply_text(f"🔍 Buscando <b>Ley Nº {html.escape(numero)}</b> en ISILeg...", parse_mode="HTML")
    try:
        data = await api.search_leyes(numero_ley=numero, page=0, page_size=1)
        items = data.get("data", [])
        if not items:
            await msg.edit_text(
                f"❌ No se encontró ninguna ley con el número <b>{html.escape(numero)}</b> en la base de datos de ISILeg.",
                parse_mode="HTML"
            )
            return

        id_ley = items[0]["idLey"]
        detail = await api.get_ley_detail(id_ley)
        card_text = build_ley_card(detail)
        related = api.extract_related_norms(detail)

        # Construir teclado inline
        buttons = [
            [
                InlineKeyboardButton("📄 PDF Original", callback_data=f"pdf:orig:{id_ley}"),
                InlineKeyboardButton("📑 PDF Actualizado", callback_data=f"pdf:act:{id_ley}"),
            ],
            [
                InlineKeyboardButton("📋 Ficha Técnica PDF", callback_data=f"pdf:ficha:{id_ley}"),
            ]
        ]

        if related:
            buttons.append([
                InlineKeyboardButton(f"🔗 Normas Relacionadas ({len(related)})", callback_data=f"rel:{id_ley}")
            ])

        reply_markup = InlineKeyboardMarkup(buttons)
        await msg.edit_text(card_text, reply_markup=reply_markup, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error buscando ley {numero}: {e}", exc_info=True)
        err_str = str(e) or type(e).__name__
        await msg.edit_text(f"⚠️ Ocurrió un error al consultar ISILeg ({type(e).__name__}): {html.escape(err_str)}")

async def handle_search_by_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, page: int = 0, is_callback: bool = False):
    target_msg = update.callback_query.message if is_callback else None
    if not is_callback:
        target_msg = await update.message.reply_text(f"🔍 Buscando normas sobre: <i>{html.escape(query)}</i>...", parse_mode="HTML")

    try:
        data = await api.search_leyes(palabras_clave=query, page=page, page_size=PAGE_SIZE)
        cant = data.get("cant", 0)
        items = data.get("data", [])

        if cant == 0 or not items:
            text = f"❌ No se encontraron normas para la búsqueda: <b>{html.escape(query)}</b>."
            if is_callback:
                await update.callback_query.edit_message_text(text, parse_mode="HTML")
            else:
                await target_msg.edit_text(text, parse_mode="HTML")
            return

        total_pages = (cant + PAGE_SIZE - 1) // PAGE_SIZE
        header = f"📚 <b>Resultados para:</b> <i>{html.escape(query)}</i>\n"
        header += f"Se encontraron <b>{cant}</b> normas (Página {page + 1} de {total_pages}):\n\n"

        buttons = []
        for item in items:
            t = item.get("texto") or f"Ley Nº {item.get('numeroLey')}"
            asunto = item.get("asunto") or ""
            if len(asunto) > 60:
                asunto = asunto[:57] + "..."
            
            btn_label = f"⚖️ {t} - {asunto}" if asunto else f"⚖️ {t}"
            buttons.append([InlineKeyboardButton(btn_label, callback_data=f"view:{item['idLey']}")])

        # Botones de paginación
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"p:{page-1}:{query[:30]}"))
        if page + 1 < total_pages:
            nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"p:{page+1}:{query[:30]}"))

        if nav_buttons:
            buttons.append(nav_buttons)

        reply_markup = InlineKeyboardMarkup(buttons)
        if is_callback:
            await update.callback_query.edit_message_text(header, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await target_msg.edit_text(header, reply_markup=reply_markup, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error buscando por tema {query}: {e}", exc_info=True)
        err_msg = f"⚠️ Ocurrió un error al realizar la búsqueda: {html.escape(str(e))}"
        if is_callback:
            await update.callback_query.edit_message_text(err_msg)
        else:
            await target_msg.edit_text(err_msg)

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    try:
        if data.startswith("view:"):
            id_ley = int(data.split(":")[1])
            await show_ley_card_callback(query, id_ley)

        elif data.startswith("pdf:"):
            parts = data.split(":")
            pdf_type = parts[1] # orig, act, ficha
            id_ley = int(parts[2])
            await handle_pdf_download(query, context, id_ley, pdf_type)

        elif data.startswith("rel:"):
            id_ley = int(data.split(":")[1])
            await show_related_norms_callback(query, id_ley)

        elif data.startswith("search_rel:"):
            nro = data.split(":")[1]
            data_ley = await api.search_leyes(numero_ley=nro, page=0, page_size=1)
            items = data_ley.get("data", [])
            if items:
                await show_ley_card_callback(query, items[0]["idLey"])
            else:
                await query.message.reply_text(f"⚠️ No se encontró la ficha directa para la Ley Nº {nro}.")

        elif data.startswith("p:"):
            parts = data.split(":", 2)
            page = int(parts[1])
            search_query = parts[2]
            await handle_search_by_topic(update, context, search_query, page=page, is_callback=True)

    except Exception as e:
        logger.error(f"Error en callback {data}: {e}", exc_info=True)
        await query.message.reply_text(f"⚠️ Error procesando la acción: {html.escape(str(e))}")

async def show_ley_card_callback(callback_query, id_ley: int):
    detail = await api.get_ley_detail(id_ley)
    card_text = build_ley_card(detail)
    related = api.extract_related_norms(detail)

    buttons = [
        [
            InlineKeyboardButton("📄 PDF Original", callback_data=f"pdf:orig:{id_ley}"),
            InlineKeyboardButton("📑 PDF Actualizado", callback_data=f"pdf:act:{id_ley}"),
        ],
        [
            InlineKeyboardButton("📋 Ficha Técnica PDF", callback_data=f"pdf:ficha:{id_ley}"),
        ]
    ]

    if related:
        buttons.append([
            InlineKeyboardButton(f"🔗 Normas Relacionadas ({len(related)})", callback_data=f"rel:{id_ley}")
        ])

    reply_markup = InlineKeyboardMarkup(buttons)
    await callback_query.edit_message_text(card_text, reply_markup=reply_markup, parse_mode="HTML")

async def show_related_norms_callback(callback_query, id_ley: int):
    detail = await api.get_ley_detail(id_ley)
    texto = detail.get("texto") or f"Ley Nº {detail.get('numeroLey')}"
    related = api.extract_related_norms(detail)

    if not related:
        await callback_query.edit_message_text(
            f"ℹ️ La norma <b>{html.escape(texto)}</b> no tiene modificaciones ni normas vinculadas registradas.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver a la Ley", callback_data=f"view:{id_ley}")]]),
            parse_mode="HTML"
        )
        return

    msg = f"🔗 <b>Normas Relacionadas y Modificaciones de:</b>\n⚖️ <b>{html.escape(texto)}</b>\n\n"
    buttons = []

    # Mostrar hasta 10 normas vinculadas con botón de consulta directa
    for r in related[:10]:
        t_norma = r["tipo"]
        n_norma = r["numero"]
        ctx = r["contexto"]
        msg += f"• <b>{t_norma} Nº {n_norma}:</b> <i>{html.escape(ctx)}</i>\n\n"
        
        # Botón para consultar directamente esa norma si es ley
        if "ley" in t_norma.lower():
            buttons.append([InlineKeyboardButton(f"🔍 Ver {t_norma} Nº {n_norma}", callback_data=f"search_rel:{n_norma}")])

    if len(related) > 10:
        msg += f"<i>(Mostrando 10 de {len(related)} normas vinculadas)</i>\n"

    buttons.append([InlineKeyboardButton("⬅️ Volver a la Ley", callback_data=f"view:{id_ley}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="HTML")

async def handle_pdf_download(callback_query, context: ContextTypes.DEFAULT_TYPE, id_ley: int, pdf_type: str):
    detail = await api.get_ley_detail(id_ley)
    numero_ley = detail.get("numeroLey") or str(id_ley)

    if pdf_type == "orig":
        endpoint = f"ley/pdfFile/{id_ley}/1"
        filename = f"Ley_{numero_ley}_Original.pdf"
        caption = f"📄 <b>Texto Original</b> - Ley Nº {numero_ley}"
    elif pdf_type == "act":
        endpoint = f"ley/pdfFile/{id_ley}/1" # La versión actualizada se obtiene con /1 o mayor
        filename = f"Ley_{numero_ley}_Actualizada.pdf"
        caption = f"📑 <b>Texto Actualizado</b> - Ley Nº {numero_ley}"
    else: # ficha
        endpoint = f"ley/pdfFicha/{id_ley}"
        filename = f"Ley_{numero_ley}_FichaTecnica.pdf"
        caption = f"📋 <b>Ficha Técnica Oficial</b> - Ley Nº {numero_ley}"

    status_msg = await callback_query.message.reply_text(f"⏳ Descargando <i>{filename}</i> desde ISILeg...", parse_mode="HTML")

    try:
        pdf_bytes = await api.get_pdf_bytes(endpoint)
        if not pdf_bytes or len(pdf_bytes) == 0:
            await status_msg.edit_text(f"⚠️ El documento <b>{filename}</b> no se encuentra disponible en ISILeg.", parse_mode="HTML")
            return

        file_obj = io.BytesIO(pdf_bytes)
        file_obj.name = filename

        await context.bot.send_document(
            chat_id=callback_query.message.chat_id,
            document=file_obj,
            filename=filename,
            caption=caption,
            parse_mode="HTML"
        )
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Error descargando PDF {endpoint}: {e}", exc_info=True)
        await status_msg.edit_text(f"⚠️ Error al descargar el documento: {html.escape(str(e))}")

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("\n" + "="*70)
        print("❌ ERROR: TELEGRAM_BOT_TOKEN no configurado.")
        print("Por favor crea un archivo .env con:")
        print("TELEGRAM_BOT_TOKEN=tu_token_aqui")
        print("="*70 + "\n")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ley", ley_command))
    app.add_handler(CommandHandler("buscar", buscar_command))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    print("🚀 Bot de Telegram ISILeg iniciado y escuchando mensajes...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
