"""
Cliente de Integración con ISILeg Web (Senado de Santa Fe)
Proporciona métodos asíncronos para buscar normas, obtener detalles y descargar documentos PDF.
"""

import httpx
import re
from typing import Optional, Dict, Any, List, Union

BASE_URL = "https://isilegweb.senadosantafe.gob.ar/api"
DEFAULT_TIMEOUT = 15.0

class ISILegAPI:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }

    async def search_leyes(
        self,
        numero_ley: Optional[str] = None,
        palabras_clave: Optional[str] = None,
        asunto: Optional[str] = None,
        tipo_ley: int = 1, # 1: Ley, 2: Decreto Ley, 3: Decreto
        page: int = 0,
        page_size: int = 5,
        orden: str = "desc"
    ) -> Dict[str, Any]:
        """
        Busca leyes en ISILeg según número o palabras clave.
        """
        params = {
            "tiposLey": str(tipo_ley),
            "pagNro": str(page),
            "pagCant": str(page_size),
            "orden": orden
        }
        
        if numero_ley:
            clean_num = "".join(filter(str.isdigit, str(numero_ley)))
            if clean_num:
                params["numeroLey"] = clean_num
                
        if palabras_clave:
            params["palabrasClave"] = palabras_clave
            
        if asunto:
            params["asunto"] = asunto

        url = f"{self.base_url}/ley"
        async with httpx.AsyncClient(verify=False, timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def get_ley_by_number(self, numero_ley: str, tipo_ley: int = 1) -> Optional[Dict[str, Any]]:
        """
        Busca directamente una ley por su número exacto y devuelve el primer resultado.
        """
        data = await self.search_leyes(numero_ley=numero_ley, tipo_ley=tipo_ley, page=0, page_size=1)
        items = data.get("data", [])
        if items and len(items) > 0:
            return items[0]
        return None

    async def get_ley_detail(self, id_ley: int) -> Dict[str, Any]:
        """
        Obtiene el detalle completo de una norma mediante su ID.
        """
        url = f"{self.base_url}/ley/{id_ley}"
        async with httpx.AsyncClient(verify=False, timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            res = resp.json()
            return res.get("data", {})

    async def get_pdf_bytes(self, pdf_path: str) -> Optional[bytes]:
        """
        Descarga el stream binario de un PDF dado su sub-path (ej. 'ley/pdfFile/6684/1').
        """
        url = f"{self.base_url}/{pdf_path.lstrip('/')}"
        async with httpx.AsyncClient(verify=False, timeout=20.0) as client:
            resp = await client.get(url, headers=self.headers)
            if resp.status_code == 200 and resp.content.startswith(b"%PDF"):
                return resp.content
            return None

    def _extract_text(self, val: Any) -> str:
        if isinstance(val, str):
            return val
        elif isinstance(val, list):
            res = []
            for item in val:
                if isinstance(item, str):
                    res.append(item)
                elif isinstance(item, dict):
                    res.append(" ".join(str(v) for v in item.values() if v is not None))
            return "\n".join(res)
        elif isinstance(val, dict):
            return " ".join(str(v) for v in val.values() if v is not None)
        return ""

    def extract_related_norms(self, detail: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Analiza los campos comentario, notas, modificaciones y texto para detectar normas vinculadas/modificatorias.
        """
        related = []
        seen = set()

        text_parts = [
            self._extract_text(detail.get("comentario")),
            self._extract_text(detail.get("notas")),
            self._extract_text(detail.get("anexos")),
            self._extract_text(detail.get("modificaciones"))
        ]
        full_text = "\n".join(filter(None, text_parts))

        # Regex para detectar menciones a Leyes o Decretos
        # Ejemplos: "MODIFICADA por Ley Nº 14451", "Ley N° 12510", "Decreto Nº 1501/2026", "Decr. Nº 0287/2026"
        patterns = [
            r'(?:MODIFICAD[AO]\s+por\s+)?(Ley|Decreto\s+Ley|Decreto|Decr\.)\s+(?:N[º°\.]*\s*)?(\d+)(?:\s*/\s*(\d{2,4}))?',
            r'(?:DEROGAD[AO]\s+por\s+)?(Ley|Decreto\s+Ley|Decreto|Decr\.)\s+(?:N[º°\.]*\s*)?(\d+)(?:\s*/\s*(\d{2,4}))?',
        ]

        current_num = str(detail.get("numeroLey", ""))

        for raw_line in full_text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            for pat in patterns:
                for match in re.finditer(pat, line, re.IGNORECASE):
                    norm_type = match.group(1).title()
                    norm_num = match.group(2)
                    norm_year = match.group(3) if match.lastindex >= 3 else None

                    if norm_type.startswith("Decr"):
                        norm_type = "Decreto"

                    key = f"{norm_type}_{norm_num}"
                    if key not in seen and norm_num != current_num:
                        seen.add(key)
                        
                        start = max(0, match.start() - 20)
                        end = min(len(line), match.end() + 60)
                        context = line[start:end].strip()

                        related.append({
                            "tipo": norm_type,
                            "numero": norm_num,
                            "anio": norm_year,
                            "contexto": context,
                            "linea_completa": line
                        })

        return related
