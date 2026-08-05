import json
import unittest

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from backend.spectrum_stream import SpectrumStreamManager


class SpectrumStreamEndpointTests(unittest.TestCase):
    def test_handshake_initial_second_snapshot_and_disconnect_cleanup(self):
        current = {
            "protocol_version": 1,
            "message_type": "spectrum_snapshot",
            "session_id": "general-1",
            "scan_owner": "general",
            "running": True,
            "completed": False,
            "spectrum_preview": {"frequency_mhz": [], "power_db": []},
        }
        app = FastAPI()
        manager = SpectrumStreamManager(lambda: current.copy())

        @app.websocket("/api/spectrum/stream")
        async def stream(websocket: WebSocket):
            await websocket.accept()
            client_id = await manager.register(websocket, current.copy())
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                await manager.remove(client_id)

        self.assertIsInstance(json.dumps(current), str)
        with TestClient(app) as client:
            with client.websocket_connect("/api/spectrum/stream") as websocket:
                initial = websocket.receive_json()
                self.assertEqual(initial["protocol_version"], 1)
                self.assertEqual(initial["message_type"], "spectrum_snapshot")
                self.assertEqual(initial["session_id"], "general-1")
                self.assertEqual(initial["scan_owner"], "general")

                current["cycle_window_index"] = 2
                manager.publish_current()
                self.assertEqual(websocket.receive_json()["cycle_window_index"], 2)

        self.assertEqual(manager._clients, {})
