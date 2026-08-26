"""
Cliente de Integración con InfoLEG (Información Legislativa - República Argentina)
Ministerio de Justicia de la Nación / SAIJ
"""

import os
import re
import html
import urllib.parse
from typing import Optional, Dict, Any, List
import httpx
from bs4 import BeautifulSoup

INFOLEG_BASE_URL = "https://servicios.infoleg.gob.ar/infolegInternet"
DEFAULT_TIMEOUT = 25.0

class InfoLegAPI:
    def __init__(self, base_url: str = INFOLEG_BASE_URL):
        self.base_url = base_url
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    async def search_normas(
        self,
        tipo_norma: str = "1", # 1: Ley, 2: Decreto, 8: Decisión Adm, 3: Resolución, 4: Disposición, "": Todos
        numero: Optional[str] = None,
        anio_sancion: Optional[str] = None,
        texto: Optional[str] = None,
        dependencia: str = "",
        limit: int = 25
    ) -> List[Dict[str, Any]]:
        """
        Realiza una búsqueda en buscarNormas.do y devuelve la lista estructurada de resultados.
        """
        url = f"{self.base_url}/buscarNormas.do"
        clean_num = "".join(filter(str.isdigit, str(numero))) if numero else ""
        clean_anio = "".join(filter(str.isdigit, str(anio_sancion))) if anio_sancion else ""

        payload = {
            "tipoNorma": tipo_norma,
            "numero": clean_num,
            "anioSancion": clean_anio,
            "texto": texto or "",
            "dependencia": dependencia,
            "diaPubDesde": "",
            "mesPubDesde": "",
            "anioPubDesde": "",
            "diaPubHasta": "",
            "mesPubHasta": "",
            "anioPubHasta": "",
            "boton_buscar": "Buscar",
            "accion": "buscar"
        }

        async with httpx.AsyncClient(verify=False, timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(url, data=payload, headers=self.headers)
            content = resp.content.decode("ISO-8859-1", errors="ignore")

        return self._parse_search_results(content, limit=limit)

    def _parse_search_results(self, html_content: str, limit: int = 25) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html_content, "html.parser")
        results = []
        seen_ids = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "verNorma.do" in href:
                # Usar regex estricto para evitar coincidir con jsessionid
                match = re.search(r"[?&]id=(\d+)", href)
                if match:
                    norma_id = match.group(1)
                    if norma_id in seen_ids:
                        continue
                    seen_ids.add(norma_id)

                    parent_tr = a.find_parent("tr")
                    cells = parent_tr.find_all(["td", "th"]) if parent_tr else []
                    
                    raw_tipo = a.get_text(" ", strip=True)
                    tipo_num = " ".join(raw_tipo.split())
                    emisor = "Poder Ejecutivo / Congreso Nacional"
                    fecha_bo = ""
                    sumario = ""

                    if len(cells) >= 3:
                        c0 = " ".join(cells[0].get_text(" ", strip=True).split())
                        c1 = " ".join(cells[1].get_text(" ", strip=True).split())
                        c2 = " ".join(cells[2].get_text(" ", strip=True).split())

                        # Ignorar fila de encabezado
                        if "Número" in c0 and "Descripción" in c2:
                            continue

                        tipo_num = " ".join(a.get_text(" ", strip=True).split())
                        if not tipo_num:
                            tipo_num = c0
                        
                        fecha_bo = c1 if c1 != "------" else ""
                        sumario = c2
                    elif len(cells) == 2:
                        sumario = " ".join(cells[1].get_text(" ", strip=True).split())

                    # Extraer año
                    year_match = re.search(r"/ (\d{4})", tipo_num)
                    year_str = year_match.group(1) if year_match else ""

                    results.append({
                        "id": norma_id,
                        "jurisdiccion": "Nación",
                        "tipo_numero": tipo_num,
                        "year": year_str,
                        "emisor": emisor,
                        "fecha_bo": fecha_bo,
                        "sumario": sumario or "Sin descripción registrada",
                        "url_infoleg": f"{self.base_url}/verNorma.do?id={norma_id}"
                    })

                    if len(results) >= limit:
                        break

        return results

    async def get_norma_detail(self, id_norma: str) -> Dict[str, Any]:
        """
        Obtiene los detalles completos de la ficha de una norma nacional.
        """
        url = f"{self.base_url}/verNorma.do?id={id_norma}"
        async with httpx.AsyncClient(verify=False, timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(url)
            content = resp.content.decode("ISO-8859-1", errors="ignore")

        soup = BeautifulSoup(content, "html.parser")
        all_text = soup.get_text("\n", strip=True)
        
        nid = int(id_norma)
        r_start = (nid // 5000) * 5000
        r_end = r_start + 4999
        url_original = f"{self.base_url}/anexos/{r_start}-{r_end}/{nid}/norma.htm"
        url_actualizado = f"{self.base_url}/anexos/{r_start}-{r_end}/{nid}/texact.htm"

        has_texact = bool(soup.find("a", href=re.compile(r"texact\.htm", re.I)))

        sumario = ""
        observaciones = ""
        emisor = "Honorable Congreso de la Nación Argentina"
        fecha_sancion = ""
        fecha_bo = ""
        numero_bo = ""
        tipo_numero = f"Norma Nacional Nº {id_norma}"

        lines = [l.strip() for l in all_text.split("\n") if l.strip()]
        for idx, line in enumerate(lines):
            if "Ley" in line or "Decreto" in line or "Resolución" in line or "Disposición" in line:
                if idx + 1 < len(lines) and lines[idx+1].replace(".","").isdigit():
                    tipo_numero = f"{line} {lines[idx+1]}"
                else:
                    tipo_numero = line
            if "Resumen:" in line and idx + 1 < len(lines):
                sumario = lines[idx+1]
            if "Observaciones:" in line and idx + 1 < len(lines):
                observaciones = lines[idx+1]
            if "Boletín Oficial del" in line and idx + 1 < len(lines):
                fecha_bo = lines[idx+1]
            if "Número:" in line and idx + 1 < len(lines) and lines[idx+1].isdigit():
                numero_bo = lines[idx+1]

        modifica_a_count = 0
        modificada_por_count = 0
        for a in soup.find_all("a", href=True):
            if "verVinculos.do" in a["href"]:
                if "modo=1" in a["href"]:
                    m = re.search(r"(\d+)", a.get_text())
                    if m: modifica_a_count = int(m.group(1))
                elif "modo=2" in a["href"]:
                    m = re.search(r"(\d+)", a.get_text())
                    if m: modificada_por_count = int(m.group(1))

        # Estado de vigencia
        estado = "🟢 Vigente (Original)"
        if observaciones and ("abrogad" in observaciones.lower() or "derogad" in observaciones.lower()):
            estado = "🔴 Abrogada / Derogada"
        elif has_texact:
            estado = f"🟡 Texto Actualizado ({modificada_por_count} modificaciones)" if modificada_por_count > 0 else "🟢 Texto Actualizado"

        return {
            "id": id_norma,
            "jurisdiccion": "Nación",
            "tipo_numero": " ".join(tipo_numero.split()),
            "emisor": emisor,
            "fecha_sancion": fecha_sancion,
            "fecha_bo": fecha_bo,
            "numero_bo": numero_bo,
            "sumario": sumario or "Sin sumario registrado",
            "observaciones": observaciones,
            "estado": estado,
            "url_infoleg": url,
            "url_original": url_original,
            "url_actualizado": url_actualizado if has_texact else None,
            "has_texact": has_texact,
            "modifica_a_count": modifica_a_count,
            "modificada_por_count": modificada_por_count
        }

    async def get_vinculos(self, id_norma: str, modo: int = 2) -> List[Dict[str, Any]]:
        """
        modo=1: Normas que esta norma modifica/deroga.
        modo=2: Normas que modifican/derogan/reglamentan a esta norma.
        """
        url = f"{self.base_url}/verVinculos.do?modo={modo}&id={id_norma}"
        async with httpx.AsyncClient(verify=False, timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(url)
            content = resp.content.decode("ISO-8859-1", errors="ignore")

        soup = BeautifulSoup(content, "html.parser")
        vinculos = []

        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) >= 3:
                c0 = " ".join(cells[0].get_text(" ", strip=True).split())
                c1 = " ".join(cells[1].get_text(" ", strip=True).split())
                c2 = " ".join(cells[2].get_text(" ", strip=True).split())
                
                if "Número" in c0 or "Fecha" in c1:
                    continue

                a_tag = tr.find("a", href=re.compile(r"verNorma\.do"))
                nid = ""
                if a_tag:
                    match = re.search(r"[?&]id=(\d+)", a_tag["href"])
                    if match:
                        nid = match.group(1)

                vinculos.append({
                    "id": nid,
                    "tipo_numero": c0,
                    "fecha": c1,
                    "descripcion": c2
                })
        return vinculos

    async def get_texto_limpio(self, id_norma: str, prefer_actualizado: bool = True) -> Optional[str]:
        """
        Descarga el HTML de la norma y extrae el texto formateado en texto plano limpio.
        Si no hay archivo HTML externo (leyes históricas), genera el resumen estructurado de la norma.
        """
        detail = await self.get_norma_detail(id_norma)
        target_url = detail.get("url_actualizado") if (prefer_actualizado and detail.get("has_texact")) else detail.get("url_original")
        
        if target_url:
            try:
                async with httpx.AsyncClient(verify=False, timeout=DEFAULT_TIMEOUT) as client:
                    resp = await client.get(target_url)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        content = resp.content.decode("ISO-8859-1", errors="ignore")
                        soup = BeautifulSoup(content, "html.parser")
                        for tag in soup(["script", "style", "nav", "header", "footer"]):
                            tag.decompose()
                        text = soup.get_text("\n", strip=True)
                        clean_text = re.sub(r"\n{3,}", "\n\n", text)
                        return clean_text
            except Exception:
                pass

        # Fallback: Construir texto descriptivo completo desde la ficha de InfoLEG
        fallback_text = (
            f"{detail.get('tipo_numero')}\n"
            f"Emisor: {detail.get('emisor')}\n"
            f"Boletín Oficial: {detail.get('fecha_bo')} (B.O. Nº {detail.get('numero_bo')})\n"
            f"Estado: {detail.get('estado')}\n\n"
            f"SUMARIO:\n{detail.get('sumario')}\n"
        )
        if detail.get("observaciones"):
            fallback_text += f"\nOBSERVACIONES:\n{detail.get('observaciones')}\n"

        return fallback_text
