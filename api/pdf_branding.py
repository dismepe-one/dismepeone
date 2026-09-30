from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from fastapi import Response
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute


ROOT = Path(__file__).resolve().parents[1]
LOGO_FILE = ROOT / "frontend" / "app-icon-v2-192.png"
FRONTEND_PATCH = ROOT / "frontend" / "pdf-branding.js"


def _route_for(app: Any, path: str, method: str) -> APIRoute | None:
    wanted = method.upper()
    for route in list(app.router.routes):
        if isinstance(route, APIRoute) and route.path == path and wanted in route.methods:
            return route
    return None


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _install_reportlab_branding() -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception:
        return

    if getattr(SimpleDocTemplate.build, "__dismepe_pdf_branding__", False):
        return

    original_build = SimpleDocTemplate.build

    def branded_build(self, flowables, *args, **kwargs):
        story = list(flowables or [])
        if not any(getattr(item, "__dismepe_brand_flowable__", False) for item in story[:3]):
            try:
                logo = Image(str(LOGO_FILE), width=11 * mm, height=11 * mm)
                wordmark = Paragraph(
                    "<b>DISMEPE ONE</b><br/><font size='6' color='#60756e'>RELATÓRIO OFICIAL</font>",
                    ParagraphStyle(
                        "DismepeOnePdfBrand",
                        fontName="Helvetica",
                        fontSize=12,
                        leading=11,
                        textColor=colors.HexColor("#145c49"),
                        spaceAfter=0,
                    ),
                )
                header = Table([[logo, wordmark]], colWidths=[14 * mm, None], hAlign="LEFT")
                header.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe7e2")),
                ]))
                setattr(header, "__dismepe_brand_flowable__", True)
                story = [header, Spacer(1, 3 * mm)] + story
            except Exception:
                pass
        return original_build(self, story, *args, **kwargs)

    branded_build.__dismepe_pdf_branding__ = True
    SimpleDocTemplate.build = branded_build


def install_pdf_branding(app: Any) -> None:
    if getattr(app.state, "pdf_branding_installed", False):
        return
    app.state.pdf_branding_installed = True

    if _route_for(app, "/dismepe-one-logo.png", "GET") is None:
        async def dismepe_one_logo():
            return FileResponse(
                LOGO_FILE,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"},
            )
        app.add_api_route(
            "/dismepe-one-logo.png",
            dismepe_one_logo,
            methods=["GET"],
            include_in_schema=False,
        )

    script_route = _route_for(app, "/update-center-prod4.js", "GET")
    if script_route is not None:
        original_script = script_route.endpoint

        async def update_center_with_pdf_branding():
            base_response = await _await_if_needed(original_script())
            base_content = getattr(base_response, "body", b"")
            if isinstance(base_content, bytes):
                base_text = base_content.decode("utf-8")
            else:
                base_text = str(base_content or "")
            branding_patch = FRONTEND_PATCH.read_text(encoding="utf-8")
            return Response(
                content=(base_text + "\n\n" + branding_patch),
                media_type="application/javascript",
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "X-DISMEPE-PDF-Branding": "DISMEPE_ONE_V1",
                },
            )

        script_route.endpoint = update_center_with_pdf_branding
        script_route.dependant.call = update_center_with_pdf_branding

    _install_reportlab_branding()
