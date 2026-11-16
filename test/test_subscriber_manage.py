#!/usr/bin/env python3
"""subscriber_manage.py 핵심 로직(등록/멱등/정원/해제) self-check. 네트워크 호출 없음."""
import subscriber_manage as sm


def _fake_call(updates):
    def call(token, method, params, **kwargs):
        if method == "getUpdates":
            return {"ok": True, "result": updates}
        return {"ok": True, "result": {}}
    return call


def test_start_registers_new_subscriber():
    original = sm._call
    sm._call = _fake_call([
        {"update_id": 1, "message": {"text": "/start", "chat": {"id": 111, "type": "private", "first_name": "A"}}},
    ])
    try:
        state = {"last_update_id": 0, "subscribers": []}
        logs = sm.process_updates("tok", state, max_subscribers=10)
        assert len(state["subscribers"]) == 1
        assert state["subscribers"][0]["chat_id"] == 111
        assert state["last_update_id"] == 1
        assert "신규 등록" in logs[0]
    finally:
        sm._call = original


def test_start_is_idempotent():
    original = sm._call
    sm._call = _fake_call([
        {"update_id": 2, "message": {"text": "/start", "chat": {"id": 111, "type": "private"}}},
    ])
    try:
        state = {"last_update_id": 1, "subscribers": [{"chat_id": 111, "first_name": "A", "username": None, "joined_at_kst": "x"}]}
        logs = sm.process_updates("tok", state, max_subscribers=10)
        assert len(state["subscribers"]) == 1
        assert "이미 구독" in logs[0]
    finally:
        sm._call = original


def test_start_rejected_when_full():
    original = sm._call
    sm._call = _fake_call([
        {"update_id": 3, "message": {"text": "/start", "chat": {"id": 222, "type": "private"}}},
    ])
    try:
        state = {"last_update_id": 2, "subscribers": [{"chat_id": 111, "first_name": "A", "username": None, "joined_at_kst": "x"}]}
        logs = sm.process_updates("tok", state, max_subscribers=1)
        assert len(state["subscribers"]) == 1
        assert "정원" in logs[0]
    finally:
        sm._call = original


def test_kicked_removes_subscriber():
    original = sm._call
    sm._call = _fake_call([
        {"update_id": 4, "my_chat_member": {"chat": {"id": 111}, "new_chat_member": {"status": "kicked"}}},
    ])
    try:
        state = {"last_update_id": 3, "subscribers": [{"chat_id": 111, "first_name": "A", "username": None, "joined_at_kst": "x"}]}
        logs = sm.process_updates("tok", state, max_subscribers=10)
        assert state["subscribers"] == []
        assert "제거" in logs[0]
    finally:
        sm._call = original


if __name__ == "__main__":
    test_start_registers_new_subscriber()
    test_start_is_idempotent()
    test_start_rejected_when_full()
    test_kicked_removes_subscriber()
    print("OK")
