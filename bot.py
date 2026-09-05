"""
Bot de Telegram Unificado para Información Legislativa:
- 🏛️ ISILeg (Poder Legislativo y Decretos Provinciales - Santa Fe)
- 🏢 SIN & Boletín Oficial de Santa Fe (Poder Ejecutivo Provincial)
- 🇦🇷 InfoLEG (República Argentina / Nivel Federal)
- 🚀 Servidor HTTP Asíncrono Unificado: Webhook Nativo + /logs + /healthz (Puerto 8080)

Desarrollado para Domingo Rondina por Antigravity.
"""

import os
import io
import json
import html
import asyncio
import logging
import re
import time
import collections
from datetime import datetime
from aiohttp import web
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

# --- Buffer Circular de Logs en Memoria ---
MAX_LOG_ENTRIES = 200
live_log_buffer = collections.deque(maxlen=MAX_LOG_ENTRIES)

class LiveLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            live_log_buffer.append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "msg": msg
            })
        except Exception:
            pass

# Logging
log_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

live_handler = LiveLogHandler()
live_handler.setFormatter(log_formatter)
root_logger.addHandler(live_handler)

logger = logging.getLogger(__name__)

# APIs
isileg_api = ISILegAPI()
infoleg_api = InfoLegAPI()
sin_api = SantaFeSINAPI()

# --- Helpers ---

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
    numero = detail.get("numero", "S/N")
    year = detail.get("year", "")
    fecha = detail.get("fecha", "No disponible")
    sumario = detail.get("sumario", "Sin sumario registrado")
    emisor = detail.get("emisor", "Poder Ejecutivo de la Provincia de Santa Fe")

    year_label = f" / {year}" if year else ""
    card = (
        f"🏢 <b>[Santa Fe] Decreto Provincial Nº {html.escape(str(numero))}{year_label}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏛️ <b>Emisor:</b> {html.escape(emisor)}\n"
        f"📅 <b>Fecha:</b> {html.escape(str(fecha))}\n\n"
        f"📝 <b>Sumario / Objeto:</b>\n<i>{html.escape(str(sumario))}</i>\n\n"
        f"📰 <b>Fuente Oficial:</b> Sistema de Información de Normativa (SIN) - Gobierno de Santa Fe."
    )
    return card

def build_nacion_norma_card(detail: dict) -> str:
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

# --- Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Comando /start de {user.username or user.first_name} (ID: {user.id})")
    welcome_text = (
        "👋 <b>Bienvenido al Asistente Legislativo Argentino Integral</b>\n\n"
        "Este bot consulta en tiempo real tres fuentes jurídicas oficiales:\n"
        "• 🏛️ <b>ISILeg</b>: Leyes y Decretos de la <b>Provincia de Santa Fe</b>.\n"
        "• 🏢 <b>SIN / Boletín Oficial</b>: Decretos y Actos del <b>Poder Ejecutivo de Santa Fe</b>.\n"
        "• 🇦🇷 <b>InfoLEG</b>: Leyes, Decretos y DNU de la <b>República Argentina (Nación)</b>.\n\n"
        "🔍 <b>¿Cómo buscar?</b>\n"
        "1. <b>Por número</b>: Envía el número (ej. <code>14207</code>, <code>20744</code>, <code>2756</code>, <code>2439</code>) o con año (ej. <code>2756/2025</code>).\n"
        "2. <b>Por tema</b>: Escribe palabras clave (ej: <code>contrato de trabajo</code>, <code>salud</code>, <code>presupuesto</code>).\n\n"
        "💡 <i>Podrás descargar PDFs oficiales, leer textos actualizados y navegar genealogías legislativas.</i>"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    logger.info(f"📥 MENSAJE RECIBIDO de {user.username or user.first_name} (ID: {user.id}): '{text}'")

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

# --- Búsqueda por Número / Año ---

async def handle_unified_number_search(update: Update, context: ContextTypes.DEFAULT_TYPE, numero: str, anio: str = ""):
    busqueda_desc = f"Nº {numero}/{anio}" if anio else f"Nº {numero}"
    t_start = time.time()
    logger.info(f"🔎 INICIANDO BÚSQUEDA para {busqueda_desc}...")

    msg = await update.message.reply_text(
        f"🔍 Buscando <b>{html.escape(busqueda_desc)}</b> en todas las bases de <b>Santa Fe (ISILeg + SIN)</b> y <b>Nación (InfoLEG)</b>...",
        parse_mode="HTML"
    )

    try:
        sf_ley_task = isileg_api.search_leyes(numero_ley=numero, tipo_ley=1, page=0, page_size=5)
        sf_dec_task = isileg_api.search_leyes(numero_ley=numero, tipo_ley=3, page=0, page_size=25)
        sf_sin_task = sin_api.search_decretos(numero=numero, anio=anio)
        nac_ley_task = infoleg_api.search_normas(tipo_norma="1", numero=numero, anio_sancion=anio, limit=10)
        nac_dec_task = infoleg_api.search_normas(tipo_norma="2", numero=numero, anio_sancion=anio, limit=30)

        sf_leys, sf_decs, sf_sins, nac_leys, nac_decs = await asyncio.gather(
            sf_ley_task, sf_dec_task, sf_sin_task, nac_ley_task, nac_dec_task, return_exceptions=True
        )
    except Exception as e:
        logger.error(f"❌ Error en búsqueda paralela: {e}")
        await msg.edit_text(f"⚠️ Error al consultar las bases legislativas: {html.escape(str(e))}")
        return

    # Santa Fe Leyes
    sf_ley_items = []
    if isinstance(sf_leys, dict) and sf_leys.get("data"):
        for it in sf_leys["data"]:
            y = extract_year_from_dates(it.get("fechaSancion"), it.get("fechaPromulgacion"))
            if not anio or (anio and y == anio):
                it["_year"] = y
                sf_ley_items.append(it)

    # Santa Fe Decretos (ISILeg + SIN)
    sf_dec_items = []
    seen_sf_years = set()

    if isinstance(sf_decs, dict) and sf_decs.get("data"):
        for it in sf_decs["data"]:
            y = extract_year_from_dates(it.get("fechaSancion"), it.get("fechaPromulgacion"))
            if not anio or (anio and y == anio):
                it["_year"] = y
                seen_sf_years.add(y)
                sf_dec_items.append(it)

    if isinstance(sf_sins, list):
        for sin_item in sf_sins:
            y = sin_item.get("year", "")
            sf_dec_items.append({
                "idLey": sin_item["id"],
                "numeroLey": numero,
                "asunto": sin_item.get("sumario", "Decreto Provincial SIN"),
                "_year": y,
                "_is_sin": True,
                "_detail": sin_item
            })

    nac_ley_items = nac_leys if isinstance(nac_leys, list) else []
    nac_dec_items = nac_decs if isinstance(nac_decs, list) else []

    total_opciones = len(sf_ley_items) + len(sf_dec_items) + len(nac_ley_items) + len(nac_dec_items)
    t_elapsed = time.time() - t_start
    logger.info(f"✅ BÚSQUEDA COMPLETADA en {t_elapsed:.2f}s: SF Leyes={len(sf_ley_items)}, SF Decretos={len(sf_dec_items)}, Nac Leyes={len(nac_ley_items)}, Nac Decretos={len(nac_dec_items)} (Total: {total_opciones})")

    if total_opciones == 0:
        await msg.edit_text(
            f"❌ No se encontró ninguna norma con el {html.escape(busqueda_desc)} en Santa Fe ni en Nación.",
            parse_mode="HTML"
        )
        return

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

    buttons = []
    item_num = 1
    menu_lines = []

    # 1. Santa Fe - Leyes
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

    # 2. Santa Fe - Decretos (SIN / ISILeg)
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
            sin_id = item["idLey"]
            buttons.append([InlineKeyboardButton(btn_label, callback_data=f"sfdec:sin:{sin_id}")])
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

    # 4. Nación - Decretos
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
        buttons = []
        
        row1 = []
        if detail.get("url_boletin_pdf"):
            row1.append(InlineKeyboardButton("📰 PDF Boletín Oficial", url=detail["url_boletin_pdf"]))
        row1.append(InlineKeyboardButton("🌐 Ver en Portal SIN", url=detail.get("url_portal", "https://www.santafe.gov.ar/normativa/")))
        buttons.append(row1)

        reply_markup = InlineKeyboardMarkup(buttons)
        await target_msg.edit_text(card_text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error mostrando decreto SIN: {e}")
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

# --- Búsqueda Temática ---

async def handle_search_by_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    user = update.effective_user
    logger.info(f"🔎 Búsqueda temática '{query}' por {user.username or user.first_name}")

    msg = await update.message.reply_text(
        f"🔍 Buscando <i>'{html.escape(query)}'</i> en Santa Fe (ISILeg + SIN) y Nación (InfoLEG)...",
        parse_mode="HTML"
    )

    try:
        sf_task = isileg_api.search_leyes(palabras_clave=query, page=0, page_size=3)
        sin_task = sin_api.search_by_text(query, limit=3)
        nac_task = infoleg_api.search_normas(tipo_norma="", texto=query, limit=3)

        sf_res, sin_res, nac_res = await asyncio.gather(sf_task, sin_task, nac_task, return_exceptions=True)
    except Exception as e:
        await msg.edit_text(f"⚠️ Error al buscar: {html.escape(str(e))}")
        return

    sf_items = sf_res.get("data", []) if isinstance(sf_res, dict) else []
    sin_items = sin_res if isinstance(sin_res, list) else []
    nac_items = nac_res if isinstance(nac_res, list) else []

    if not sf_items and not sin_items and not nac_items:
        await msg.edit_text(f"❌ No se encontraron resultados para <i>'{html.escape(query)}'</i>.", parse_mode="HTML")
        return

    buttons = []
    text_resp = f"📚 <b>Resultados para:</b> <i>'{html.escape(query)}'</i>\n\n"

    if sf_items:
        text_resp += "🏛️ <b>Provincia de Santa Fe (Leyes):</b>\n"
        for item in sf_items:
            num = item.get("numeroLey", "S/N")
            asunto = (item.get("asunto") or "")[:60]
            text_resp += f"• <b>Ley Prov. {num}</b>: {html.escape(asunto)}...\n"
            buttons.append([InlineKeyboardButton(f"🏛️ Ver Ley Prov. Nº {num}", callback_data=f"sf:card:{item['idLey']}")])
        text_resp += "\n"

    if sin_items:
        text_resp += "🏢 <b>Provincia de Santa Fe (Decretos del Ejecutivo - SIN):</b>\n"
        for item in sin_items:
            num = item.get("numero", "S/N")
            yr = item.get("year", "")
            yr_str = f"/{yr}" if yr else ""
            sumario = (item.get("sumario") or "")[:60]
            text_resp += f"• <b>Decreto Prov. {num}{yr_str}</b>: {html.escape(sumario)}...\n"
            buttons.append([InlineKeyboardButton(f"🏢 Ver Dto {num}{yr_str}", callback_data=f"sfdec:sin:{item['id']}")])
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

# --- Callbacks ---

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    user = update.effective_user
    logger.info(f"🖱️ CALLBACK recibido de {user.username or user.first_name}: {data}")

    # 1. Tarjetas Directas
    if data.startswith("sf:card:"):
        id_ley = int(data.split(":")[2])
        await show_sf_ley_card(query.message, id_ley)
        return
    elif data.startswith("sfdec:sin:"):
        sin_id = data[len("sfdec:sin:"):]
        detail = sin_api.get_cached_detail(sin_id)
        if detail:
            await show_sf_decreto_sin_card_direct(query.message, detail)
        else:
            parts = sin_id.split("_")
            num = parts[1] if len(parts) > 1 else ""
            yr = parts[2] if len(parts) > 2 else ""
            await show_sf_decreto_sin_card_direct(query.message, {
                "numero": num,
                "year": yr,
                "sumario": "Decreto registrado en el Sistema de Información de Normativa (SIN)",
                "emisor": "Poder Ejecutivo de la Provincia de Santa Fe"
            })
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

    # 4. Modificaciones InfoLEG
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

    # 5. Relaciones Santa Fe
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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"❌ ERROR NO CONTROLADO en update ({update}): {context.error}", exc_info=context.error)

# --- Servidor Webhook + Logs + Health Check Asíncrono Unificado (aiohttp) ---

async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN no configurado.")
        return

    port = int(os.getenv("PORT", "8080"))
    external_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_URL") or "https://isileg-telegram-bot.onrender.com"
    webhook_path = f"/{token}"
    full_webhook_url = f"{external_url.rstrip('/')}{webhook_path}"

    logger.info("Iniciando Bot Legislativo con Servidor Webhook + Logs Integrado...")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("ayuda", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)

    # Iniciar la aplicación de telegram
    await app.initialize()
    await app.start()
    
    current_webhook = await app.bot.get_webhook_info()
    if current_webhook.url != full_webhook_url:
        await app.bot.set_webhook(url=full_webhook_url, drop_pending_updates=False)
        logger.info(f"Webhook registrado en Telegram: {full_webhook_url}")
    else:
        logger.info(f"Webhook ya activo y verificado: {full_webhook_url}")

    # Definir rutas en aiohttp
    routes = web.RouteTableDef()

    @routes.get("/")
    @routes.get("/healthz")
    async def health_check(request):
        return web.Response(text="OK - Asistente Legislativo Activo", content_type="text/plain")

    @routes.get("/logs")
    async def logs_view(request):
        html_out = "<html><head><title>Logs en Vivo - Asistente Legislativo</title>"
        html_out += "<style>body{font-family:monospace;background:#1e1e1e;color:#d4d4d4;padding:20px;} .item{margin-bottom:8px;border-bottom:1px solid #333;padding-bottom:4px;} .INFO{color:#4ec9b0;} .ERROR{color:#f44747;} .time{color:#888;}</style></head><body>"
        html_out += "<h2>📊 Registro de Eventos en Vivo (Últimos 200 eventos)</h2>"
        if not live_log_buffer:
            html_out += "<p>No hay eventos registrados aún en esta sesión.</p>"
        else:
            for entry in reversed(live_log_buffer):
                lvl = entry.get("level", "INFO")
                tm = entry.get("time", "")
                msg = html.escape(entry.get("msg", ""))
                html_out += f"<div class='item'><span class='time'>[{tm}]</span> <span class='{lvl}'>[{lvl}]</span> {msg}</div>"
        html_out += "</body></html>"
        return web.Response(text=html_out, content_type="text/html")

    @routes.post(webhook_path)
    async def telegram_webhook(request):
        try:
            req_data = await request.json()
            update = Update.de_json(req_data, app.bot)
            
            # Verificación de Lista Blanca (Silencio total si no es el administrador)
            sender_id = None
            if update.effective_user:
                sender_id = str(update.effective_user.id)
            elif update.effective_chat:
                sender_id = str(update.effective_chat.id)

            if sender_id != "510179444":
                return web.Response(text="OK", status=200)

            # Procesar el update en segundo plano sin trabar la respuesta HTTP
            asyncio.create_task(app.process_update(update))
            return web.Response(text="OK", status=200)
        except Exception as e:
            logger.error(f"Error procesando webhook de Telegram: {e}")
            return web.Response(text="Error", status=500)

    web_app = web.Application()
    web_app.add_routes(routes)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Servidor Webhook + Logs corriendo en http://0.0.0.0:{port}")

    # Mantener corriendo
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
