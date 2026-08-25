"""
Bot de Telegram Unificado para Información Legislativa:
- ISILeg (Provincia de Santa Fe)
- InfoLEG (República Argentina / Nivel Federal)

Desarrollado para Domingo Rondina por Antigravity.
"""

import os
import io
import html
import asyncio
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from isileg_api import ISILegAPI
from infoleg_api import InfoLegAPI

load_dotenv()

# Configuración de Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Instancias de API
isileg_api = ISILegAPI()
infoleg_api = InfoLegAPI()

# --- Servidor HTTP para Render Health Check ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz" or self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        elif self.path == "/test":
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                data = loop.run_until_complete(isileg_api.search_leyes("14207"))
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(str(data).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(f"Error: {e}".encode("utf-8"))
            finally:
                loop.close()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def run_health_server(port: int = 8080):
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"Servidor HTTP de Health Check escuchando en puerto {port}")
    server.serve_forever()

# --- Formateadores de Mensajes ---

def build_sf_ley_card(detail: dict) -> str:
    """Construye la tarjeta de una Ley de Santa Fe."""
    num_ley = detail.get("numeroLey", "S/N")
    asunto = detail.get("asunto") or "Sin asunto registrado"
    fecha_sancion = detail.get("fechaSancion") or "No disponible"
    fecha_prom = detail.get("fechaPromulgacion") or "No disponible"
    fecha_bo = detail.get("fechaPublicacionBo") or "No disponible"
    num_bo = detail.get("numeroBo") or "-"
    num_exp = detail.get("numeroExpediente") or "-"

    estado = "🟢 Vigente"
    comentario = detail.get("comentario") or ""
    if "derogad" in comentario.lower():
        estado = "🔴 Derogada"
    elif "modificad" in comentario.lower():
        estado = "🟡 Modificada"

    card = (
        f"🏛️ <b>[Santa Fe] Ley Provincial Nº {html.escape(str(num_ley))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Estado:</b> {estado}\n"
        f"📅 <b>Sanción:</b> {html.escape(str(fecha_sancion))}\n"
        f"📜 <b>Promulgación:</b> {html.escape(str(fecha_prom))}\n"
        f"📰 <b>Boletín Oficial:</b> {html.escape(str(fecha_bo))} (B.O. Nº {html.escape(str(num_bo))})\n"
        f"📁 <b>Expediente:</b> {html.escape(str(num_exp))}\n\n"
        f"📝 <b>Asunto:</b>\n<i>{html.escape(str(asunto))}</i>\n"
    )

    if comentario:
        card += f"\n📌 <b>Notas / Modificaciones:</b>\n{html.escape(str(comentario))[:400]}\n"

    return card

def build_nacion_norma_card(detail: dict) -> str:
    """Construye la tarjeta de una Norma Nacional (InfoLEG)."""
    tipo_num = detail.get("tipo_numero") or f"Norma ID {detail.get('id')}"
    emisor = detail.get("emisor") or "Poder Ejecutivo / Congreso Nacional"
    fecha_bo = detail.get("fecha_bo") or "No disponible"
    num_bo = detail.get("numero_bo") or "-"
    sumario = detail.get("sumario") or "Sin sumario registrado"
    has_texact = detail.get("has_texact", False)
    modificada_por = detail.get("modificada_por_count", 0)
    modifica_a = detail.get("modifica_a_count", 0)

    estado = "🟢 Vigente (Original)"
    if has_texact:
        estado = f"🟡 Texto Actualizado ({modificada_por} modificaciones)" if modificada_por > 0 else "🟢 Texto Actualizado"

    card = (
        f"🇦🇷 <b>[Nación] {html.escape(str(tipo_num))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <b>Emisor:</b> {html.escape(str(emisor))}\n"
        f"📰 <b>Boletín Oficial:</b> {html.escape(str(fecha_bo))} (B.O. Nº {html.escape(str(num_bo))})\n"
        f"📊 <b>Estado:</b> {estado}\n"
    )

    if modifica_a > 0:
        card += f"🔄 <b>Modifica a:</b> {modifica_a} norma(s)\n"

    card += f"\n📝 <b>Sumario:</b>\n<i>{html.escape(str(sumario))}</i>\n"
    return card

# --- Handlers de Comandos y Mensajes ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 <b>Bienvenido al Asistente Legislativo Argentino</b>\n\n"
        "Este bot consulta en tiempo real dos de las bases jurídicas más completas del país:\n"
        "• 🏛️ <b>ISILeg</b>: Legislación de la <b>Provincia de Santa Fe</b>.\n"
        "• 🇦🇷 <b>InfoLEG</b>: Leyes, Decretos y DNU de la <b>República Argentina (Nación)</b>.\n\n"
        "🔍 <b>¿Cómo buscar?</b>\n"
        "1. <b>Por número</b>: Envía solo el número (ej. <code>14207</code>, <code>20744</code>, <code>26994</code> o <code>70</code>). "
        "Si existen leyes provinciales y decretos/leyes nacionales con el mismo número, podrás elegir cuál ver.\n"
        "2. <b>Por tema</b>: Escribe palabras clave (ej: <code>contrato de trabajo</code>, <code>bioquimicos</code>, <code>presupuesto</code>).\n\n"
        "💡 <i>Podrás descargar PDFs oficiales, leer textos actualizados y navegar normas relacionadas.</i>"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return

    # Si es puramente numérico (ej. "14207", "70", "20744")
    clean_num = "".join(filter(str.isdigit, text))
    if clean_num and clean_num == text.replace(".", ""):
        await handle_unified_number_search(update, context, clean_num)
    else:
        await handle_search_by_topic(update, context, text)

# --- Búsqueda Unificada por Número ---

async def handle_unified_number_search(update: Update, context: ContextTypes.DEFAULT_TYPE, numero: str):
    msg = await update.message.reply_text(
        f"🔍 Buscando <b>Nº {html.escape(numero)}</b> en <b>Santa Fe (ISILeg)</b> y <b>Nación (InfoLEG)</b>...",
        parse_mode="HTML"
    )

    # Consultar ambas fuentes en paralelo
    try:
        sf_task = isileg_api.search_leyes(numero_ley=numero, page=0, page_size=1)
        nac_ley_task = infoleg_api.search_normas(tipo_norma="1", numero=numero, limit=3)
        nac_dec_task = infoleg_api.search_normas(tipo_norma="2", numero=numero, limit=3)

        sf_res, nac_leys, nac_decs = await asyncio.gather(
            sf_task, nac_ley_task, nac_dec_task, return_exceptions=True
        )
    except Exception as e:
        logger.error(f"Error en búsqueda paralela: {e}")
        await msg.edit_text(f"⚠️ Error al consultar las bases legislativas: {html.escape(str(e))}")
        return

    # Normalizar resultados
    sf_items = []
    if isinstance(sf_res, dict) and sf_res.get("data"):
        sf_items = sf_res["data"]

    nac_ley_items = nac_leys if isinstance(nac_leys, list) else []
    nac_dec_items = nac_decs if isinstance(nac_decs, list) else []

    total_opciones = len(sf_items) + len(nac_ley_items) + len(nac_dec_items)

    if total_opciones == 0:
        await msg.edit_text(
            f"❌ No se encontró ninguna norma con el número <b>{html.escape(numero)}</b> ni en Santa Fe ni en Nación.",
            parse_mode="HTML"
        )
        return

    # Si hay una única coincidencia, mostramos la tarjeta directa
    if total_opciones == 1:
        if len(sf_items) == 1:
            await show_sf_ley_card(msg, sf_items[0]["idLey"])
            return
        elif len(nac_ley_items) == 1:
            await show_nacion_norma_card(msg, nac_ley_items[0]["id"])
            return
        elif len(nac_dec_items) == 1:
            await show_nacion_norma_card(msg, nac_dec_items[0]["id"])
            return

    # Si hay múltiples coincidencias, creamos el Menú Selector
    buttons = []

    # 1. Opción Santa Fe
    for item in sf_items:
        id_ley = item["idLey"]
        asunto_short = (item.get("asunto") or "")[:40]
        label = f"🏛️ [Santa Fe] Ley Prov. Nº {numero}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"sf:card:{id_ley}")])

    # 2. Opciones Nación - Leyes
    for item in nac_ley_items:
        nid = item["id"]
        label = f"🇦🇷 [Nación] Ley Nac. Nº {numero}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"nac:card:{nid}")])

    # 3. Opciones Nación - Decretos
    for item in nac_dec_items:
        nid = item["id"]
        tipo_lbl = item.get("tipo_numero", f"Decreto {numero}")
        label = f"🇦🇷 [Nación] {tipo_lbl[:35]}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"nac:card:{nid}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    menu_text = (
        f"🏛️ <b>Se encontraron normas coincidentes con el Nº {html.escape(numero)}:</b>\n\n"
        f"Selecciona la norma que deseas consultar:"
    )
    await msg.edit_text(menu_text, reply_markup=reply_markup, parse_mode="HTML")

# --- Renderizado de Tarjeta Santa Fe ---

async def show_sf_ley_card(target_msg, id_ley: int):
    try:
        detail = await isileg_api.get_ley_detail(id_ley)
        card_text = build_sf_ley_card(detail)
        related = isileg_api.extract_related_norms(detail)

        buttons = [
            [
                InlineKeyboardButton("📄 PDF Original", callback_data=f"sf:pdf:orig:{id_ley}"),
                InlineKeyboardButton("📑 PDF Actualizado", callback_data=f"sf:pdf:act:{id_ley}"),
            ],
            [
                InlineKeyboardButton("📋 Ficha Técnica PDF", callback_data=f"sf:pdf:ficha:{id_ley}"),
            ]
        ]
        if related:
            buttons.append([
                InlineKeyboardButton(f"🔗 Normas Relacionadas ({len(related)})", callback_data=f"sf:rel:{id_ley}")
            ])

        reply_markup = InlineKeyboardMarkup(buttons)
        await target_msg.edit_text(card_text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error mostrando tarjeta Santa Fe {id_ley}: {e}")
        await target_msg.edit_text(f"⚠️ Error al cargar detalle de Santa Fe: {html.escape(str(e))}")

# --- Renderizado de Tarjeta Nación ---

async def show_nacion_norma_card(target_msg, id_norma: str):
    try:
        detail = await infoleg_api.get_norma_detail(id_norma)
        card_text = build_nacion_norma_card(detail)

        buttons = []
        row1 = []
        if detail.get("has_texact"):
            row1.append(InlineKeyboardButton("📖 Texto Actualizado", callback_data=f"nac:txt:act:{id_norma}"))
        row1.append(InlineKeyboardButton("📜 Texto Original", callback_data=f"nac:txt:orig:{id_norma}"))
        buttons.append(row1)

        row2 = []
        mod_count = detail.get("modificada_por_count", 0)
        if mod_count > 0:
            row2.append(InlineKeyboardButton(f"🔗 Modificaciones ({mod_count})", callback_data=f"nac:rel:{id_norma}"))
        row2.append(InlineKeyboardButton("🌐 Ver en InfoLEG", url=detail.get("url_infoleg")))
        buttons.append(row2)

        reply_markup = InlineKeyboardMarkup(buttons)
        await target_msg.edit_text(card_text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error mostrando tarjeta Nación {id_norma}: {e}")
        await target_msg.edit_text(f"⚠️ Error al cargar detalle de Nación: {html.escape(str(e))}")

# --- Búsqueda Temática / Palabras Clave ---

async def handle_search_by_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    msg = await update.message.reply_text(
        f"🔍 Buscando <i>'{html.escape(query)}'</i> en Santa Fe y Nación...",
        parse_mode="HTML"
    )

    try:
        sf_task = isileg_api.search_leyes(palabras_clave=query, page=0, page_size=4)
        nac_task = infoleg_api.search_normas(tipo_norma="", texto=query, limit=4)

        sf_res, nac_res = await asyncio.gather(sf_task, nac_task, return_exceptions=True)
    except Exception as e:
        await msg.edit_text(f"⚠️ Error al buscar: {html.escape(str(e))}")
        return

    sf_items = sf_res.get("data", []) if isinstance(sf_res, dict) else []
    nac_items = nac_res if isinstance(nac_res, list) else []

    if not sf_items and not nac_items:
        await msg.edit_text(f"❌ No se encontraron resultados para <i>'{html.escape(query)}'</i>.", parse_mode="HTML")
        return

    buttons = []
    text_resp = f"📚 <b>Resultados para:</b> <i>'{html.escape(query)}'</i>\n\n"

    if sf_items:
        text_resp += "🏛️ <b>Provincia de Santa Fe:</b>\n"
        for item in sf_items:
            num = item.get("numeroLey", "S/N")
            asunto = (item.get("asunto") or "")[:60]
            text_resp += f"• <b>Ley Prov. {num}</b>: {html.escape(asunto)}...\n"
            buttons.append([InlineKeyboardButton(f"🏛️ Ver Ley Prov. Nº {num}", callback_data=f"sf:card:{item['idLey']}")])
        text_resp += "\n"

    if nac_items:
        text_resp += "🇦🇷 <b>Nación (InfoLEG):</b>\n"
        for item in nac_items:
            tipo_num = item.get("tipo_numero", f"Norma {item['id']}")
            sumario = (item.get("sumario") or "")[:60]
            text_resp += f"• <b>{html.escape(tipo_num)}</b>: {html.escape(sumario)}...\n"
            buttons.append([InlineKeyboardButton(f"🇦🇷 Ver {tipo_num[:30]}", callback_data=f"nac:card:{item['id']}")])

    reply_markup = InlineKeyboardMarkup(buttons)
    await msg.edit_text(text_resp, reply_markup=reply_markup, parse_mode="HTML")

# --- Callbacks Handler ---

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    # 1. Tarjetas Directas
    if data.startswith("sf:card:"):
        id_ley = int(data.split(":")[2])
        await show_sf_ley_card(query.message, id_ley)
        return
    elif data.startswith("nac:card:"):
        nid = data.split(":")[2]
        await show_nacion_norma_card(query.message, nid)
        return

    # 2. Descargas PDF Santa Fe
    elif data.startswith("sf:pdf:"):
        parts = data.split(":")
        pdf_type = parts[2]
        id_ley = int(parts[3])

        sub_paths = {
            "orig": f"ley/pdfFile/{id_ley}/1",
            "act": f"ley/pdfFile/{id_ley}/2",
            "ficha": f"ley/pdfFicha/{id_ley}"
        }
        sub_path = sub_paths.get(pdf_type)
        if not sub_path:
            await query.message.reply_text("❌ Tipo de documento no válido.")
            return

        status_msg = await query.message.reply_text("⏳ Descargando PDF oficial de Santa Fe...")
        pdf_bytes = await isileg_api.get_pdf_bytes(sub_path)
        await status_msg.delete()

        if pdf_bytes:
            filename = f"SantaFe_Ley_{id_ley}_{pdf_type}.pdf"
            await context.bot.send_document(
                chat_id=chat_id,
                document=io.BytesIO(pdf_bytes),
                filename=filename,
                caption=f"📄 Documento Oficial de Santa Fe (Ley ID {id_ley})"
            )
        else:
            await query.message.reply_text("⚠️ No se pudo descargar el archivo PDF solicitado.")
        return

    # 3. Textos y Modificaciones de Nación
    elif data.startswith("nac:txt:"):
        parts = data.split(":")
        tipo_txt = parts[2] # act u orig
        nid = parts[3]
        prefer_act = (tipo_txt == "act")

        status_msg = await query.message.reply_text("⏳ Obteniendo texto normativo de InfoLEG...")
        texto = await infoleg_api.get_texto_limpio(nid, prefer_actualizado=prefer_act)
        await status_msg.delete()

        if texto:
            detail = await infoleg_api.get_norma_detail(nid)
            titulo = detail.get("tipo_numero", f"Norma {nid}")
            tag = "Texto Actualizado" if prefer_act else "Texto Original"

            if len(texto) <= 3500:
                await query.message.reply_text(
                    f"📖 <b>{html.escape(titulo)} - {tag}</b>\n\n{html.escape(texto)}",
                    parse_mode="HTML"
                )
            else:
                # Enviar como archivo de texto adjunto para normas largas
                txt_bytes = texto.encode("utf-8")
                filename = f"{titulo.replace(' ', '_')}_{tag.replace(' ', '_')}.txt"
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=io.BytesIO(txt_bytes),
                    filename=filename,
                    caption=f"📜 {titulo} ({tag}) - InfoLEG"
                )
        else:
            await query.message.reply_text("⚠️ No se pudo recuperar el texto de la norma.")
        return

    # 4. Modificaciones / Vínculos de Nación
    elif data.startswith("nac:rel:"):
        nid = data.split(":")[2]
        status_msg = await query.message.reply_text("⏳ Consultando modificaciones en InfoLEG...")
        vincs = await infoleg_api.get_vinculos(nid, modo=2)
        await status_msg.delete()

        if vincs:
            msg_text = f"🔗 <b>Normas que modifican/reglamentan a esta norma ({len(vincs)}):</b>\n\n"
            for v in vincs[:10]:
                msg_text += f"• <b>{html.escape(v['tipo_numero'])}</b> ({html.escape(v['fecha'])}): {html.escape(v['asunto'][:60])}...\n"
            if len(vincs) > 10:
                msg_text += f"\n<i>...y {len(vincs)-10} modificaciones más en InfoLEG.</i>"
            await query.message.reply_text(msg_text, parse_mode="HTML")
        else:
            await query.message.reply_text("ℹ️ No se registraron modificaciones para esta norma.")
        return

    # 5. Relaciones de Santa Fe
    elif data.startswith("sf:rel:"):
        id_ley = int(data.split(":")[2])
        detail = await isileg_api.get_ley_detail(id_ley)
        related = isileg_api.extract_related_norms(detail)

        if not related:
            await query.message.reply_text("ℹ️ No se encontraron menciones directas a otras normas.")
            return

        text_rel = f"🔗 <b>Normas Relacionadas con Ley Provincial {detail.get('numeroLey')}:</b>\n\n"
        for r in related[:8]:
            text_rel += f"• <b>{r['tipo']} Nº {r['numero']}</b>\n  <i>\"{html.escape(r['contexto'])}\"</i>\n"
        await query.message.reply_text(text_rel, parse_mode="HTML")

# --- Main Application ---

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN no configurado.")
        return

    # Iniciar Health Check Server en hilo secundario para Render
    port = int(os.getenv("PORT", "8080"))
    threading.Thread(target=run_health_server, args=(port,), daemon=True).start()

    logger.info("Iniciando Bot Legislativo Unificado (Santa Fe + Nación)...")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("ayuda", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
