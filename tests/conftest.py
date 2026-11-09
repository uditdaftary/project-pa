"""Pytest configuration and shared test fixtures for Project PA."""

import pytest
from core.messages import DisplaySurface, AudioDestination, CrossSurfaceRoutingPayload
from gateway.server import engine, audio_router


@pytest.fixture(autouse=True)
def reset_engine_and_router():
    """Reset shared engine and gateway state between every test."""
    engine.router.current_display = DisplaySurface.PRIVATE_HUD
    engine.router.current_audio = AudioDestination.PRIVATE_EAR
    audio_router.active_surface_route = CrossSurfaceRoutingPayload(
        display_surface=DisplaySurface.PRIVATE_HUD,
        audio_destination=AudioDestination.PRIVATE_EAR,
        reason="test_reset",
    )
    engine.ring_buffer.drain(fade_ms=0.0)
    engine.ring_buffer.reset_playhead()
    engine.vad.reset()
    yield
    engine.router.current_display = DisplaySurface.PRIVATE_HUD
    engine.router.current_audio = AudioDestination.PRIVATE_EAR
    audio_router.active_surface_route = CrossSurfaceRoutingPayload(
        display_surface=DisplaySurface.PRIVATE_HUD,
        audio_destination=AudioDestination.PRIVATE_EAR,
        reason="test_teardown_reset",
    )
