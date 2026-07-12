"""SenseCap M1 hardware settings (fan/LED/button) for the Configuration panel.

All three peripherals only start once during app startup (src/api/server.py
lifespan), so every update here requires a service restart to take effect --
same convention as radio/advanced and the capture-source editors.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.api.audit import AuditLogWriter
from src.api.audit.dependencies import get_audit_writer
from src.api.auth.dependencies import require_admin
from src.api.auth.jwt_session import SessionClaims
from src.config import AppConfig, save_section_to_yaml

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config/hardware", tags=["config"])

_config: AppConfig | None = None


def init_routes(config: AppConfig) -> None:
    global _config
    _config = config


def reset_routes() -> None:
    global _config
    _config = None


class FanHardwareUpdate(BaseModel):
    enabled: bool = False
    gpio_pin: int = Field(13, ge=0, le=27)
    min_temp_c: float = 45.0
    max_temp_c: float = 65.0
    min_duty: float = Field(0.35, ge=0.0, le=1.0)
    hysteresis_c: float = Field(5.0, ge=0.0)
    poll_interval_s: float = Field(10.0, gt=0.0)

    @field_validator("max_temp_c")
    @classmethod
    def _max_above_min(cls, value: float, info) -> float:
        min_temp_c = info.data.get("min_temp_c")
        if min_temp_c is not None and value <= min_temp_c:
            raise ValueError("max_temp_c must be greater than min_temp_c")
        return value


class LedHardwareUpdate(BaseModel):
    enabled: bool = False
    gpio_pin: int = Field(22, ge=0, le=27)
    activity_blink: bool = True


class ButtonHardwareUpdate(BaseModel):
    enabled: bool = False
    gpio_pin: int = Field(27, ge=0, le=27)
    hold_time_s: float = Field(3.0, gt=0.0)
    advert_cooldown_s: float = Field(30.0, ge=0.0)


@router.put("/fan")
async def update_fan(
    req: FanHardwareUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    updates = req.model_dump()
    with audit.timed_action(
        user=_claims.subject, action="config.hardware_fan_update", params=updates
    ):
        fan = _config.fan
        fan.enabled = req.enabled
        fan.gpio_pin = req.gpio_pin
        fan.min_temp_c = req.min_temp_c
        fan.max_temp_c = req.max_temp_c
        fan.min_duty = req.min_duty
        fan.hysteresis_c = req.hysteresis_c
        fan.poll_interval_s = req.poll_interval_s
        try:
            save_section_to_yaml("fan", updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    logger.info("Fan hardware config updated: enabled=%s gpio_pin=%s", req.enabled, req.gpio_pin)
    return {"saved": True, "restart_required": True, "updates": updates}


@router.put("/led")
async def update_led(
    req: LedHardwareUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    updates = req.model_dump()
    with audit.timed_action(
        user=_claims.subject, action="config.hardware_led_update", params=updates
    ):
        led = _config.led
        led.enabled = req.enabled
        led.gpio_pin = req.gpio_pin
        led.activity_blink = req.activity_blink
        try:
            save_section_to_yaml("led", updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    logger.info("LED hardware config updated: enabled=%s gpio_pin=%s", req.enabled, req.gpio_pin)
    return {"saved": True, "restart_required": True, "updates": updates}


@router.put("/button")
async def update_button(
    req: ButtonHardwareUpdate,
    _claims: SessionClaims = Depends(require_admin),
    audit: AuditLogWriter = Depends(get_audit_writer),
):
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    updates = req.model_dump()
    with audit.timed_action(
        user=_claims.subject, action="config.hardware_button_update", params=updates
    ):
        button = _config.button
        button.enabled = req.enabled
        button.gpio_pin = req.gpio_pin
        button.hold_time_s = req.hold_time_s
        button.advert_cooldown_s = req.advert_cooldown_s
        try:
            save_section_to_yaml("button", updates)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    logger.info(
        "Button hardware config updated: enabled=%s gpio_pin=%s", req.enabled, req.gpio_pin,
    )
    return {"saved": True, "restart_required": True, "updates": updates}
