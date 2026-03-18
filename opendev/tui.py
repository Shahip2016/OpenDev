"""
Terminal User Interface (TUI) built on Textual (Section 2.1).

Features:
  - Sidebar for session management.
  - Main chat area with Markdown support.
  - Status bar with token and cost tracking.
  - Modal approval dialogs for tool execution.
"""

from __future__ import annotations

from typing import Any, Optional
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static, Markdown
from textual.binding import Binding

from opendev.models import Message, Role


class ApprovalModal(ModalScreen[bool]):
    """Modal dialog for tool approval (Layer 3)."""

    def __init__(self, tool_name: str, details: str, risk: str):
        super().__init__()
        self.tool_name = tool_name
        self.details = details
        self.risk = risk

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label(f"Approval Required: {self.tool_name}", id="modal-title")
            yield Static(self.details, id="modal-details")
            yield Label(f"Risk Level: {self.risk}", id="modal-risk")
            with Horizontal(id="modal-buttons"):
                yield Button("Approve (y)", variant="success", id="approve")
                yield Button("Reject (n)", variant="error", id="reject")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "approve":
            self.dismiss(True)
        else:
            self.dismiss(False)


class ChatMessage(Static):
    """A single message in the chat area."""

    def __init__(self, message: Message):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        role_label = f"[{'bold blue' if self.message.role == Role.USER else 'bold green'}]{self.message.role.value.upper()}[/]"
        yield Label(role_label)
        yield Markdown(self.message.content or "")
        if self.message.tool_calls:
            yield Static(f"🛠️ [dim]Tool Calls: {', '.join(tc.name for tc in self.message.tool_calls)}[/]")


class ChatScreen(Screen):
    """Main chat screen with sidebar and input."""

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("tab", "focus_next", "Next"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("SESSIONS", id="sidebar-label")
                self.session_list = ListView(id="sessions")
                yield self.session_list
            with Vertical(id="chat-area"):
                self.chat_history = Container(id="history")
                yield self.chat_history
                yield Input(placeholder="Type your task here...", id="query-input")
        yield Footer()

    def add_message(self, message: Message) -> None:
        self.chat_history.mount(ChatMessage(message))
        self.chat_history.scroll_end()


class OpenDevTUI(App):
    """Main Textual Application for OpenDev."""

    CSS = """
    #sidebar {
        width: 30;
        background: $panel;
        border-right: tall $primary;
    }
    #sidebar-label {
        padding: 1;
        background: $primary;
        color: white;
        text-align: center;
        text-style: bold;
    }
    #history {
        height: 1fr;
        overflow-y: scroll;
        padding: 1;
    }
    #query-input {
        margin: 1;
        border: tall $primary;
    }
    #modal-dialog {
        width: 60;
        height: auto;
        background: $surface;
        border: alert $error;
        padding: 1;
        align: center middle;
    }
    #modal-title {
        text-style: bold;
        color: orange;
        margin-bottom: 1;
    }
    #modal-buttons {
        margin-top: 1;
        align: center middle;
    }
    ChatMessage {
        margin-bottom: 1;
        padding: 1;
        border: solid $accent;
    }
    """

    def __init__(self, agent_suite: Any, config: Any):
        super().__init__()
        self.suite = agent_suite
        self.config = config

    def on_mount(self) -> None:
        self.push_screen(ChatScreen())

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
            return
        
        query = event.value
        event.input.value = ""
        
        screen = self.get_screen("ChatScreen")
        # In a real app, this would run agent loop in a thread
        # and use call_from_thread to update UI.
        # For this implementation, we just mock the display.
        screen.add_message(Message(role=Role.USER, content=query))
        
        # Trigger agent (stubs)
        response = self.suite.main_agent.run_sync(query)
        screen.add_message(Message(role=Role.ASSISTANT, content=response))


def launch_tui(suite: Any, config: Any) -> None:
    """Launch the OpenDev TUI."""
    app = OpenDevTUI(suite, config)
    app.run()
