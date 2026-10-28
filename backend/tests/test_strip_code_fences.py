"""Claude often wraps JSON in a ```json fence even when asked not to."""

from app.utils.llm_client import strip_code_fences


def test_plain_json_unchanged():
    assert strip_code_fences('{"a": 1}') == '{"a": 1}'


def test_json_fence_removed():
    assert strip_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_bare_fence_removed():
    assert strip_code_fences('  ```\n{"a": 1}\n```  ') == '{"a": 1}'


def test_none_becomes_empty():
    assert strip_code_fences(None) == ''
