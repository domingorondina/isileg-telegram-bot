"""
Bot de Telegram Unificado para Información Legislativa:
- 🏛️ ISILeg (Poder Legislativo y Decretos Provinciales - Santa Fe)
- 🏢 SIN & Boletín Oficial de Santa Fe (Poder Ejecutivo Provincial)
- 🇦🇷 InfoLEG (República Argentina / Nivel Federal)

Desarrollado para Domingo Rondina por Antigravity.
"""

import os
import io
import html
import asyncio
import logging
import re
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
from santafe_sin_api import SantaFeSINAPI

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
sin_api = SantaFeSINAPI()

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

def extract_year_from_dates(*dates) -> str:
    for d in dates:
        if d:
            m = re.search(r"(\d{4})", str(d))
            if m:
                return m.group(1)
    return ""

def shorten_text(text: str, max_len: int = 35) -> str:
    if not text:
        return ""
    clean = " ".join(text.split())
    if len(clean) > max_len:
        return clean[:max_len-3] + "..."
    return clean

def build_sf_ley_card(detail: dict) -> str:
    """Construye la tarjeta de una Ley o Decreto de Santa Fe (ISILeg)."""
    num_ley = detail.get("numeroLey", "S/N")
    asunto = detail.get("asunto") or "Sin asunto registrado"
    fecha_sancion = detail.get("fechaSancion") or "No disponible"
    fecha_prom = detail.get("fechaPromulgacion") or "No disponible"
    fecha_bo = detail.get("fechaPublicacionBo") or "No disponible"
    num_bo = detail.get("numeroBo") or "-"
    num_exp = detail.get("numeroExpediente") or "-"

    tipo_norma = "Ley Provincial"
    tipo_id = detail.get("tipoLey") or detail.get("tipo", 1)
    if str(tipo_id) == "3" or "decreto" in str(detail.get("texto", "")).lower():
        tipo_norma = "Decreto Provincial"
    elif str(tipo_id) == "2":
        tipo_norma = "Decreto Ley Provincial"

    estado = "🟢 Vigente"
    comentario = detail.get("comentario") or ""
    if "derogad" in comentario.lower():
        estado = "🔴 Derogada"
    elif "modificad" in comentario.lower():
        estado = "🟡 Modificada"

    card = (
        f"🏛️ <b>[Santa Fe] {tipo_norma} Nº {html.escape(str(num_ley))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Estado:</b> {estado}\n"
        f"📅 <b>Fecha / Sanción:</b> {html.escape(str(fecha_sancion))}\n"
    )
    if fecha_prom != "No disponible" and fecha_prom:
        card += f"📜 <b>Promulgación:</b> {html.escape(str(fecha_prom))}\n"
    if fecha_bo != "No disponible" and fecha_bo:
        card += f"📰 <b>Boletín Oficial:</b> {html.escape(str(fecha_bo))} (B.O. Nº {html.escape(str(num_bo))})\n"
    if num_exp != "-":
        card += f"📁 <b>Expediente:</b> {html.escape(str(num_exp))}\n"

    card += f"\n📝 <b>Asunto / Tema:</b>\n<i>{html.escape(str(asunto))}</i>\n"

    if comentario:
        card += f"\n📌 <b>Notas / Modificaciones:</b>\n{html.escape(str(comentario))[:400]}\n"

    return card

def build_sf_decreto_sin_card(detail: dict) -> str:
    """Construye la tarjeta de un Decreto Provincial de Santa Fe recuperado de SIN."""
    numero = detail.get("numero", "S/N")
    year = detail.get("year", "")
    fecha = detail.get("fecha", "No disponible")
    sumario = detail.get("sumario", "Sin sumario")

    card = (
        f"🏢 <b>[Santa Fe - Poder Ejecutivo] Decreto Provincial Nº {html.escape(str(numero))}/{html.escape(str(year))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <b>Emisor:</b> Poder Ejecutivo de la Provincia de Santa Fe\n"
        f"📅 <b>Fecha / Publicación:</b> {html.escape(str(fecha))}\n\n"
        f"📝 <b>Sumario / Objeto:</b>\n<i>{html.escape(str(sumario))}</i>\n\n"
        f"📰 <b>Fuentes Oficiales:</b> Boletín Oficial de Santa Fe y Sistema SIN."
    )
    return card

def build_sf_decreto_generico_card(numero: str, anio: str = "") -> str:
    """Construye la tarjeta de consulta para Decretos del Poder Ejecutivo de Santa Fe."""
    decreto_title = f"Decretos Provinciales Nº {numero}/{anio}" if anio else f"Decretos Provinciales Nº {numero}"
    card = (
        f"🏢 <b>[Santa Fe - Poder Ejecutivo] {html.escape(decreto_title)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <b>Emisor:</b> Poder Ejecutivo de la Provincia de Santa Fe (Gobernación y Ministerios)\n"
        f"📅 <b>Régimen de Emisión Anual:</b> En Santa Fe los decretos se numeran del 1 al 4000+ en cada ejercicio anual independiente.\n\n"
        f"💡 <b>Para buscar un año específico:</b> Envía el mensaje con formato <code>{numero}/AAAA</code> (ej: <code>{numero}/2023</code> o <code>{numero}/2019</code>).\n\n"
        f"📰 <b>Fuentes Oficiales:</b> Boletín Oficial de Santa Fe y Sistema SIN."
    )
    return card

def build_nacion_norma_card(detail: dict) -> str:
    """Construye la tarjeta de una Norma Nacional (InfoLEG)."""
    raw_tipo = detail.get("tipo_numero") or f"Norma ID {detail.get('id')}"
    tipo_num = " ".join(raw_tipo.split())
    emisor = detail.get("emisor") or "Poder Ejecutivo / Congreso Nacional"
    fecha_bo = detail.get("fecha_bo") or "No disponible"
    num_bo = detail.get("numero_bo") or "-"
    sumario = detail.get("sumario") or "Sin sumario registrado"
    observaciones = detail.get("observaciones") or ""
    estado = detail.get("estado", "🟢 Vigente (Original)")
    modificada_por = detail.get("modificada_por_count", 0)
    modifica_a = detail.get("modifica_a_count", 0)

    card = (
        f"🇦🇷 <b>[Nación] {html.escape(str(tipo_num))}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <b>Emisor:</b> {html.escape(str(emisor))}\n"
        f"📰 <b>Boletín Oficial:</b> {html.escape(str(fecha_bo))} (B.O. Nº {html.escape(str(num_bo))})\n"
        f"📊 <b>Estado:</b> {estado}\n"
    )

    if modifica_a > 0:
        card += f"🔄 <b>Modifica o complementa a:</b> {modifica_a} norma(s)\n"
    if modificada_por > 0:
        card += f"⚠️ <b>Modificada/Abrogada por:</b> {modificada_por} norma(s)\n"

    card += f"\n📝 <b>Sumario / Tema:</b>\n<i>{html.escape(str(sumario))}</i>\n"

    if observaciones:
        card += f"\n📌 <b>Observaciones / Vigencia:</b>\n<b>{html.escape(str(observaciones))}</b>\n"

    return card

# --- Handlers de Comandos y Mensajes ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 <b>Bienvenido al Asistente Legislativo Argentino Integral</b>\n\n"
        "Este bot consulta en tiempo real tres fuentes jurídicas oficiales:\n"
        "• 🏛️ <b>ISILeg</b>: Leyes y Decretos de la <b>Provincia de Santa Fe</b>.\n"
        "• 🏢 <b>SIN / Boletín Oficial</b>: Actos y Decretos del <b>Poder Ejecutivo de Santa Fe</b>.\n"
        "• 🇦🇷 <b>InfoLEG</b>: Leyes, Decretos y DNU de la <b>República Argentina (Nación)</b>.\n\n"
        "🔍 <b>¿Cómo buscar?</b>\n"
        "1. <b>Por número</b>: Envía el número (ej. <code>14207</code>, <code>20744</code>, <code>2756</code>) o número con año (ej. <code>2751/2008</code>, <code>70/2023</code>).\n"
        "2. <b>Por tema</b>: Escribe palabras clave (ej: <code>contrato de trabajo</code>, <code>salud</code>, <code>presupuesto</code>).\n\n"
        "💡 <i>Podrás descargar PDFs oficiales, leer textos actualizados y navegar genealogías legislativas.</i>"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return

    norma_match = re.match(r"^(\d{1,6})(?:\s*[/–-]\s*(\d{2,4}))?$", text.replace(".", ""))
    if norma_match:
        numero = norma_match.group(1)
        anio = norma_match.group(2) or ""
        if len(anio) == 2:
            anio = f"20{anio}" if int(anio) < 50 else f"19{anio}"
        await handle_unified_number_search(update, context, numero, anio)
    else:
        await handle_search_by_topic(update, context, text)

# --- Búsqueda Unificada Exhaustiva por Número / Año ---

async def handle_unified_number_search(update: Update, context: ContextTypes.DEFAULT_TYPE, numero: str, anio: str = ""):
    busqueda_desc = f"Nº {numero}/{anio}" if anio else f"Nº {numero}"
    msg = await update.message.reply_text(
        f"🔍 Buscando <b>{html.escape(busqueda_desc)}</b> en todas las bases de <b>Santa Fe</b> y <b>Nación</b>...",
        parse_mode="HTML"
    )

    try:
        # Búsqueda simultánea en todas las fuentes
        sf_ley_task = isileg_api.search_leyes(numero_ley=numero, tipo_ley=1, page=0, page_size=5)
        sf_dec_task = isileg_api.search_leyes(numero_ley=numero, tipo_ley=3, page=0, page_size=25)
        sf_sin_task = sin_api.search_decretos(numero=numero, anio=anio)
        nac_ley_task = infoleg_api.search_normas(tipo_norma="1", numero=numero, anio_sancion=anio, limit=10)
        nac_dec_task = infoleg_api.search_normas(tipo_norma="2", numero=numero, anio_sancion=anio, limit=30)

        sf_leys, sf_decs, sf_sins, nac_leys, nac_decs = await asyncio.gather(
            sf_ley_task, sf_dec_task, sf_sin_task, nac_ley_task, nac_dec_task, return_exceptions=True
        )
    except Exception as e:
        logger.error(f"Error en búsqueda paralela: {e}")
        await msg.edit_text(f"⚠️ Error al consultar las bases legislativas: {html.escape(str(e))}")
        return

    # Normalizar resultados Santa Fe Leyes
    sf_ley_items = []
    if isinstance(sf_leys, dict) and sf_leys.get("data"):
        for it in sf_leys["data"]:
            y = extract_year_from_dates(it.get("fechaSancion"), it.get("fechaPromulgacion"))
            if not anio or (anio and y == anio):
                it["_year"] = y
                sf_ley_items.append(it)

    # Normalizar resultados Santa Fe Decretos (ISILeg + SIN)
    sf_dec_items = []
    seen_sf_years = set()

    if isinstance(sf_decs, dict) and sf_decs.get("data"):
        for it in sf_decs["data"]:
            y = extract_year_from_dates(it.get("fechaSancion"), it.get("fechaPromulgacion"))
            if not anio or (anio and y == anio):
                it["_year"] = y
                seen_sf_years.add(y)
                sf_dec_items.append(it)

    # Integrar resultados de SIN Santa Fe si el backend provincial responde
    if isinstance(sf_sins, list):
        for sin_item in sf_sins:
            y = sin_item.get("year", "")
            if y not in seen_sf_years:
                sf_dec_items.append({
                    "idLey": sin_item["id"],
                    "numeroLey": numero,
                    "asunto": sin_item.get("sumario", "Decreto Provincial SIN"),
                    "_year": y,
                    "_is_sin": True,
                    "_detail": sin_item
                })
                seen_sf_years.add(y)

    nac_ley_items = nac_leys if isinstance(nac_leys, list) else []
    nac_dec_items = nac_decs if isinstance(nac_decs, list) else []

    total_opciones = len(sf_ley_items) + len(sf_dec_items) + len(nac_ley_items) + len(nac_dec_items)

    if total_opciones == 0:
        await msg.edit_text(
            f"❌ No se encontró ninguna norma con el {html.escape(busqueda_desc)} en Santa Fe ni en Nación.",
            parse_mode="HTML"
        )
        return

    # Si hay una única coincidencia, mostramos la tarjeta directa
    if total_opciones == 1:
        if len(sf_ley_items) == 1:
            await show_sf_ley_card(msg, sf_ley_items[0]["idLey"])
            return
        elif len(sf_dec_items) == 1:
            if sf_dec_items[0].get("_is_sin"):
                await show_sf_decreto_sin_card_direct(msg, sf_dec_items[0]["_detail"])
            else:
                await show_sf_ley_card(msg, sf_dec_items[0]["idLey"])
            return
        elif len(nac_ley_items) == 1:
            await show_nacion_norma_card(msg, nac_ley_items[0]["id"])
            return
        elif len(nac_dec_items) == 1:
            await show_nacion_norma_card(msg, nac_dec_items[0]["id"])
            return

    # Construir listado de todas las normas encontradas con su año y sumario
    buttons = []
    item_num = 1
    menu_lines = []

    # 1. Santa Fe - Leyes Provinciales
    for item in sf_ley_items:
        id_ley = item["idLey"]
        y_str = f" ({item['_year']})" if item.get("_year") else ""
        asunto = item.get("asunto") or "Sin asunto registrado"
        asunto_short = shorten_text(asunto, 32)

        menu_lines.append(
            f"<b>{item_num}. 🏛️ [Santa Fe] Ley Provincial Nº {numero}{y_str}</b>\n"
            f"   📝 <i>{html.escape(asunto[:120])}</i>\n"
        )
        btn_label = f"🏛️ [SF] Ley {numero}{y_str}: {asunto_short}"
        buttons.append([InlineKeyboardButton(btn_label, callback_data=f"sf:card:{id_ley}")])
        item_num += 1

    # 2. Santa Fe - Decretos Provinciales (ISILeg / SIN)
    for item in sf_dec_items:
        id_ley = item["idLey"]
        y_str = f" / {item['_year']}" if item.get("_year") else ""
        asunto = item.get("asunto") or "Sin asunto registrado"
        asunto_short = shorten_text(asunto, 32)

        menu_lines.append(
            f"<b>{item_num}. 🏢 [Santa Fe] Decreto Provincial Nº {numero}{y_str}</b>\n"
            f"   📝 <i>{html.escape(asunto[:120])}</i>\n"
        )
        btn_label = f"🏢 [SF] Dto {numero}{y_str}: {asunto_short}"
        if item.get("_is_sin"):
            buttons.append([InlineKeyboardButton(btn_label, callback_data=f"sfdec:gen:{numero}:{item.get('_year','')}")])
        else:
            buttons.append([InlineKeyboardButton(btn_label, callback_data=f"sf:card:{id_ley}")])
        item_num += 1

    # 3. Nación - Leyes
    for item in nac_ley_items:
        nid = item["id"]
        tipo_lbl = " ".join(item.get("tipo_numero", f"Ley {numero}").split())
        sumario = item.get("sumario") or "Sin descripción registrada"
        sumario_short = shorten_text(sumario, 32)

        menu_lines.append(
            f"<b>{item_num}. 🇦🇷 [Nación] {html.escape(tipo_lbl)}</b>\n"
            f"   📝 <i>{html.escape(sumario[:120])}</i>\n"
        )
        btn_label = f"🇦🇷 [Nac] {tipo_lbl}: {sumario_short}"
        buttons.append([InlineKeyboardButton(btn_label, callback_data=f"nac:card:{nid}")])
        item_num += 1

    # 4. Nación - Todos los Decretos de cada año
    for item in nac_dec_items:
        nid = item["id"]
        tipo_lbl = " ".join(item.get("tipo_numero", f"Decreto {numero}").split())
        sumario = item.get("sumario") or "Sin descripción registrada"
        sumario_short = shorten_text(sumario, 32)

        menu_lines.append(
            f"<b>{item_num}. 🇦🇷 [Nación] {html.escape(tipo_lbl)}</b>\n"
            f"   📝 <i>{html.escape(sumario[:120])}</i>\n"
        )
        btn_label = f"🇦🇷 [Nac] {tipo_lbl}: {sumario_short}"
        buttons.append([InlineKeyboardButton(btn_label, callback_data=f"nac:card:{nid}")])
        item_num += 1

    menu_text = f"🏛️ <b>Se encontraron {total_opciones} normas con el {html.escape(busqueda_desc)}:</b>\n\n"
    menu_text += "\n".join(menu_lines)
    menu_text += "\n👇 <i>Toca la norma deseada para ver el texto completo y descargas:</i>"

    if len(menu_text) > 4000:
        menu_text = menu_text[:3900] + "\n\n<i>...y más opciones en los botones inferiores.</i>"

    reply_markup = InlineKeyboardMarkup(buttons)
    await msg.edit_text(menu_text, reply_markup=reply_markup, parse_mode="HTML")

# --- Renderizado de Tarjetas ---

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

async def show_sf_decreto_sin_card_direct(target_msg, detail: dict):
    try:
        card_text = build_sf_decreto_sin_card(detail)
        buttons = [
            [
                InlineKeyboardButton("📰 Boletín Oficial de Santa Fe", url="https://www.santafe.gob.ar/boletinoficial/"),
                InlineKeyboardButton("🌐 Portal SIN Santa Fe", url="https://www.santafe.gov.ar/normativa/"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await target_msg.edit_text(card_text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error mostrando decreto SIN: {e}")
        await target_msg.edit_text(f"⚠️ Error: {html.escape(str(e))}")

async def show_sf_decreto_generico_card(target_msg, numero: str, anio: str = ""):
    try:
        card_text = build_sf_decreto_generico_card(numero, anio)
        buttons = [
            [
                InlineKeyboardButton("📰 Boletín Oficial de Santa Fe", url="https://www.santafe.gob.ar/boletinoficial/"),
                InlineKeyboardButton("🌐 Portal SIN Santa Fe", url="https://www.santafe.gov.ar/normativa/"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await target_msg.edit_text(card_text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error mostrando decreto genérico Santa Fe {numero}: {e}")
        await target_msg.edit_text(f"⚠️ Error: {html.escape(str(e))}")

async def show_nacion_norma_card(target_msg, id_norma: str):
    try:
        detail = await infoleg_api.get_norma_detail(id_norma)
        card_text = build_nacion_norma_card(detail)

        buttons = []
        row1 = []
        if detail.get("has_texact"):
            row1.append(InlineKeyboardButton("📖 Texto Actualizado", callback_data=f"nac:txt:act:{id_norma}"))
        row1.append(InlineKeyboardButton("📜 Ver Texto Completo", callback_data=f"nac:txt:orig:{id_norma}"))
        buttons.append(row1)

        row2 = []
        total_mod = detail.get("modificada_por_count", 0) + detail.get("modifica_a_count", 0)
        if total_mod > 0:
            row2.append(InlineKeyboardButton(f"🔗 Modificaciones / Vínculos ({total_mod})", callback_data=f"nac:rel:{id_norma}"))
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
        sf_task = isileg_api.search_leyes(palabras_clave=query, page=0, page_size=3)
        nac_task = infoleg_api.search_normas(tipo_norma="", texto=query, limit=3)

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
            raw_t = item.get("tipo_numero", f"Norma {item['id']}")
            tipo_num = " ".join(raw_t.split())
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
    elif data.startswith("sfdec:gen:"):
        parts = data.split(":")
        num = parts[2]
        anio = parts[3] if len(parts) > 3 else ""
        await show_sf_decreto_generico_card(query.message, num, anio)
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
            filename = f"SantaFe_Norma_{id_ley}_{pdf_type}.pdf"
            await context.bot.send_document(
                chat_id=chat_id,
                document=io.BytesIO(pdf_bytes),
                filename=filename,
                caption=f"📄 Documento Oficial de Santa Fe (ID {id_ley})"
            )
        else:
            await query.message.reply_text("⚠️ No se pudo descargar el archivo PDF solicitado.")
        return

    # 3. Textos de Nación
    elif data.startswith("nac:txt:"):
        parts = data.split(":")
        tipo_txt = parts[2]
        nid = parts[3]
        prefer_act = (tipo_txt == "act")

        status_msg = await query.message.reply_text("⏳ Obteniendo texto normativo de InfoLEG...")
        texto = await infoleg_api.get_texto_limpio(nid, prefer_actualizado=prefer_act)
        await status_msg.delete()

        if texto:
            detail = await infoleg_api.get_norma_detail(nid)
            titulo = " ".join(detail.get("tipo_numero", f"Norma {nid}").split())
            tag = "Texto Actualizado" if prefer_act else "Texto Completo"

            if len(texto) <= 3500:
                await query.message.reply_text(
                    f"📖 <b>{html.escape(titulo)} - {tag}</b>\n\n{html.escape(texto)}",
                    parse_mode="HTML"
                )
            else:
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

    # 4. Modificaciones / Vínculos de Nación (modo 1 y modo 2 unificados)
    elif data.startswith("nac:rel:"):
        nid = data.split(":")[2]
        status_msg = await query.message.reply_text("⏳ Consultando modificaciones y vínculos en InfoLEG...")
        v1_task = infoleg_api.get_vinculos(nid, modo=1)
        v2_task = infoleg_api.get_vinculos(nid, modo=2)
        v1, v2 = await asyncio.gather(v1_task, v2_task, return_exceptions=True)
        await status_msg.delete()

        v1_list = v1 if isinstance(v1, list) else []
        v2_list = v2 if isinstance(v2, list) else []

        if v1_list or v2_list:
            msg_text = f"🔗 <b>Genealogía Normativa y Modificaciones (InfoLEG):</b>\n\n"
            if v1_list:
                msg_text += f"🔄 <b>Normas que esta norma modifica/complementa ({len(v1_list)}):</b>\n"
                for v in v1_list[:6]:
                    tipo_limpio = " ".join(v['tipo_numero'].split())
                    msg_text += f"• <b>{html.escape(tipo_limpio)}</b> ({html.escape(v['fecha'])}): {html.escape(v['descripcion'][:60])}\n"
                msg_text += "\n"
            if v2_list:
                msg_text += f"⚠️ <b>Normas que modifican/abrogan/reglamentan a esta norma ({len(v2_list)}):</b>\n"
                for v in v2_list[:6]:
                    tipo_limpio = " ".join(v['tipo_numero'].split())
                    msg_text += f"• <b>{html.escape(tipo_limpio)}</b> ({html.escape(v['fecha'])}): {html.escape(v['descripcion'][:60])}\n"
            
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

# --- Webhook & Health Check Server ---

class WebhookAndHealthHandler(BaseHTTPRequestHandler):
    app_instance = None
    app_loop = None
    token_path = ""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_POST(self):
        path_clean = self.path.strip("/")
        if self.token_path and path_clean == self.token_path.strip("/"):
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode("utf-8"))
                update = Update.de_json(data, self.app_instance.bot)
                if self.app_loop and self.app_instance:
                    asyncio.run_coroutine_threadsafe(
                        self.app_instance.process_update(update), self.app_loop
                    )
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"OK")
            except Exception as e:
                logger.error(f"Error procesando update de Webhook: {e}", exc_info=True)
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

async def run_webhook_app(app, token: str, external_url: str, port: int):
    await app.initialize()
    await app.start()

    WebhookAndHealthHandler.app_instance = app
    WebhookAndHealthHandler.app_loop = asyncio.get_running_loop()
    WebhookAndHealthHandler.token_path = token

    server = HTTPServer(("0.0.0.0", port), WebhookAndHealthHandler)
    logger.info(f"Servidor Webhook + Health Check escuchando en puerto {port}")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    await asyncio.sleep(1)

    full_webhook_url = f"{external_url.rstrip('/')}/{token}"
    logger.info(f"Registrando Webhook en Telegram: {full_webhook_url}")
    await app.bot.set_webhook(url=full_webhook_url, drop_pending_updates=True)

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await app.stop()
        await app.shutdown()

# --- Main Application ---

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN no configurado.")
        return

    port = int(os.getenv("PORT", "8080"))
    bot_mode = os.getenv("BOT_MODE", "webhook").lower()
    external_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_URL")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("ayuda", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    if bot_mode == "webhook" and external_url:
        logger.info("Iniciando Bot Legislativo Unificado en MODO WEBHOOK...")
        asyncio.run(run_webhook_app(app, token, external_url, port))
    else:
        logger.info("Iniciando Bot Legislativo Unificado en MODO POLLING...")
        threading.Thread(target=run_health_server, args=(port,), daemon=True).start()
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
