"""Offline tests for the Clippy module: the chat endpoint goes only through the agent."""

from __future__ import annotations

from pathlib import Path


def test_web_chat_endpoint_uses_only_agent_chat() -> None:
    import ast

    import stock_ontology.web.clippy.routes as web_app

    tree = ast.parse(Path(web_app.__file__).read_text(encoding="utf-8"))
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "chat_endpoint"
    ]
    assert len(handlers) == 1
    handler = handlers[0]

    agent_names = {
        target.id
        for node in ast.walk(handler)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "OntologyAgent"
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert agent_names, "chat_endpoint must construct an OntologyAgent"

    attrs = {
        node.attr
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in agent_names
    }
    assert attrs == {"chat"}

    # The agent object is used only as the receiver of `.chat`, never passed or read otherwise.
    chat_receivers = {
        id(node.value)
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute) and node.attr == "chat"
    }
    other_uses = [
        node.lineno
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
        and node.id in agent_names
        and isinstance(node.ctx, ast.Load)
        and id(node) not in chat_receivers
    ]
    assert other_uses == []
