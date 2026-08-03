import asyncio
import unittest

from backend.spectrum_stream import SpectrumStreamManager


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.release = asyncio.Event()

    async def send_json(self, message):
        await self.release.wait()
        self.sent.append(message)


class SpectrumStreamManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_queues_the_current_identity_snapshot(self):
        manager = SpectrumStreamManager(lambda: {
            "session_id": "specific-7",
            "scan_owner": "specific",
            "selected_machine_id": 7,
        })
        socket = FakeSocket()
        client_id = await manager.register(socket)
        snapshot = manager._clients[client_id].queue.get_nowait()

        self.assertEqual(snapshot["session_id"], "specific-7")
        self.assertEqual(snapshot["scan_owner"], "specific")
        self.assertEqual(snapshot["selected_machine_id"], 7)
        await manager.remove(client_id)

    async def test_registration_replacement_and_cleanup(self):
        manager = SpectrumStreamManager(lambda: {"session_id": "one", "scan_owner": "general"})
        socket = FakeSocket()
        client_id = await manager.register(socket)
        client = manager._clients[client_id]

        manager.publish_current()
        manager.publish_current()

        self.assertEqual(client.queue.qsize(), 1)
        self.assertGreaterEqual(manager.replaced_frames, 1)
        self.assertEqual(client.queue.get_nowait()["session_id"], "one")

        await manager.remove(client_id)
        self.assertNotIn(client_id, manager._clients)

    async def test_slow_client_never_blocks_publication_and_sends_latest_frame(self):
        sequence = iter((
            {"session_id": "old", "scan_owner": "general"},
            {"session_id": "new", "scan_owner": "specific", "completed": True},
        ))
        manager = SpectrumStreamManager(lambda: next(sequence))
        socket = FakeSocket()
        client_id = await manager.register(socket, {"session_id": "initial"})

        manager.publish_current()
        manager.publish_current()
        self.assertEqual(manager._clients[client_id].queue.qsize(), 1)
        self.assertGreaterEqual(manager.replaced_frames, 1)

        socket.release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(socket.sent[-1]["session_id"], "new")
        self.assertTrue(socket.sent[-1]["completed"])
        await manager.shutdown()

    async def test_threadsafe_publish_only_schedules_event_loop_work(self):
        manager = SpectrumStreamManager(lambda: {"session_id": "one"})
        calls = []

        class Loop:
            def is_closed(self):
                return False

            def call_soon_threadsafe(self, callback):
                calls.append(callback)

        manager.bind_event_loop(Loop())
        self.assertTrue(manager.publish_threadsafe())
        self.assertEqual(calls, [manager.publish_current])

    async def test_stopped_completed_and_error_snapshots_remain_publishable(self):
        transitions = iter((
            {"session_id": "one", "running": False, "completed": True, "last_error": None},
            {"session_id": "one", "running": False, "completed": False, "last_error": "USB disconnected"},
        ))
        manager = SpectrumStreamManager(lambda: next(transitions))
        socket = FakeSocket()
        client_id = await manager.register(socket, {"session_id": "one", "running": True})

        manager.publish_current()
        manager.publish_current()
        latest = manager._clients[client_id].queue.get_nowait()
        self.assertFalse(latest["running"])
        self.assertEqual(latest["last_error"], "USB disconnected")
        await manager.shutdown()
