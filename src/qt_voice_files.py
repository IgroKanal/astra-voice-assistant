"""Voice-runtime file IPC for the Qt workspace, using existing bounded schemas."""
from __future__ import annotations

import os
from pathlib import Path
import threading
import time

from src.desktop_file_search import (
    make_file_open_result, make_file_question_result, make_file_read_result,
    make_search_result, parse_file_request, spoken_document_chunk,
)


class QtVoiceFileController:
    def __init__(self, bridge):
        self.bridge = bridge
        self.workspace = None
        self._lock = threading.RLock()
        self._generation = 0
        self._jobs = {}

    def set_workspace(self, workspace):
        with self._lock:
            self._generation += 1
            self.cancel()
            self._jobs.clear()
            self.workspace = workspace

    def cancel(self):
        with self._lock:
            for cancellation, _generation in self._jobs.values():
                cancellation.set()

    def handle(self, operation, text):
        try:
            parsed_operation, request = parse_file_request(text)
        except ValueError:
            return
        if parsed_operation != operation:
            return
        request_id = request["request_id"]
        query = request.get("filename", request.get("query", ""))
        question = request.get("question", "")
        read_offset = request.get("offset", 0)
        requested_generation = request.get("workspace_generation", 0)
        runtime_process = self.bridge.process
        with self._lock:
            workspace = self.workspace
            generation = self._generation
            if workspace is None:
                self.bridge.reply_file_request(
                    self._result(operation, request_id, "no_workspace"),
                    expected_process=runtime_process,
                )
                return
            if operation == "read" and (read_offset > 0 or requested_generation > 0):
                if not requested_generation or requested_generation != generation:
                    self.bridge.reply_file_request(
                        make_file_read_result(request_id, "cancelled"),
                        expected_process=runtime_process,
                    )
                    return
            cancellation = threading.Event()
            self._jobs[request_id] = (cancellation, generation)

        def work():
            status = "ok"
            entries = []
            relative_path = ""
            filename = ""
            excerpt = ""
            private_answer = ""
            next_offset = 0
            has_more = False
            deadline = time.monotonic() + 8.0
            try:
                if operation == "question":
                    from src.desktop_settings import DesktopSettings
                    from src.file_rag import FileQuestionSession
                    profile = DesktopSettings().load()
                    if profile.provider != "ollama" or "ask_files" not in profile.allowed_scopes:
                        status = "local_model_required"
                    else:
                        entries = workspace.find_exact_name(query, is_cancelled=cancellation.is_set, deadline=deadline)
                        if not entries:
                            status = "not_found"
                        elif len(entries) > 1:
                            status = "ambiguous"
                        else:
                            relative_path = entries[0].path
                            candidate = Path(relative_path)
                            if candidate.suffix.casefold() not in workspace.READABLE_SUFFIXES:
                                status = "unsafe_file"
                            else:
                                workspace.checked_readable_file(relative_path)
                                timeout_cancelled = threading.Event()
                                timeout_timer = threading.Timer(40.0, timeout_cancelled.set)
                                timeout_timer.daemon = True
                                timeout_timer.start()
                                try:
                                    answer = FileQuestionSession(workspace, relative_path).answer(
                                        question, profile,
                                        cancelled=lambda: cancellation.is_set() or timeout_cancelled.is_set(),
                                        timeout_seconds=40.0,
                                    )
                                    if timeout_cancelled.is_set():
                                        status = "question_failed"
                                    else:
                                        citations = []
                                        for passage in answer.passages[:3]:
                                            citation = f"{Path(passage.file).name}, строки {passage.start_line}–{passage.end_line}"
                                            if citation not in citations:
                                                citations.append(citation)
                                        private_answer = answer.text
                                        if citations:
                                            private_answer += " Источники: " + "; ".join(citations) + "."
                                        filename = candidate.name
                                finally:
                                    timeout_timer.cancel()
                elif operation == "search":
                    entries = workspace.search(query, is_cancelled=cancellation.is_set, deadline=deadline)
                else:
                    entries = workspace.find_exact_name(query, is_cancelled=cancellation.is_set, deadline=deadline)
                    if not entries:
                        status = "not_found"
                    elif len(entries) > 1:
                        status = "ambiguous"
                    else:
                        relative_path = entries[0].path
                        if operation == "read":
                            candidate = Path(relative_path)
                            if candidate.suffix.casefold() not in workspace.READABLE_SUFFIXES:
                                status = "unsafe_file"
                            else:
                                workspace.checked_readable_file(relative_path)
                                document_text = workspace.read_text(relative_path, is_cancelled=cancellation.is_set, deadline=deadline)
                                excerpt, next_offset, has_more = spoken_document_chunk(document_text, read_offset)
                                filename = candidate.name
                                del document_text
            except Exception:
                status = self._failure_status(operation, cancellation)
            with self._lock:
                current = (
                    generation == self._generation and workspace is self.workspace
                    and not cancellation.is_set()
                )
                self._jobs.pop(request_id, None)
                if not current:
                    status = "cancelled"
                    entries = []
                    relative_path = filename = excerpt = private_answer = ""
                    next_offset = 0
                    has_more = False
                elif operation == "open" and status == "ok":
                    try:
                        make_file_open_result(request_id, "ok", relative_path)
                        path = workspace.checked_openable_file(relative_path)
                        if cancellation.is_set():
                            status = "cancelled"
                            relative_path = ""
                        elif not callable(getattr(os, "startfile", None)):
                            status = "open_failed"
                            relative_path = ""
                        else:
                            os.startfile(str(path))
                    except Exception:
                        status = "unsafe_file" if Path(relative_path).suffix.casefold() not in workspace.OPENABLE_SUFFIXES else "open_failed"
                        relative_path = ""
                try:
                    if operation == "open":
                        result = make_file_open_result(request_id, status, relative_path)
                    elif operation == "read":
                        result = make_file_read_result(request_id, status, filename, excerpt, next_offset, has_more, generation if status == "ok" else 0)
                    elif operation == "question":
                        result = make_file_question_result(request_id, status, filename, private_answer)
                    else:
                        result = make_search_result(request_id, status, min(len(entries), 500), [entry.path for entry in entries[:3]])
                except (TypeError, ValueError):
                    result = self._result(operation, request_id, self._failure_status(operation, cancellation))
                self.bridge.reply_file_request(result, expected_process=runtime_process)

        threading.Thread(target=work, name=f"astra-qt-file-{operation}", daemon=True).start()

    @staticmethod
    def _failure_status(operation, cancellation=None):
        if cancellation is not None and cancellation.is_set():
            return "cancelled"
        return {"search": "search_failed", "read": "read_failed", "question": "question_failed", "open": "open_failed"}[operation]

    @staticmethod
    def _result(operation, request_id, status):
        if operation == "open":
            return make_file_open_result(request_id, status)
        if operation == "read":
            return make_file_read_result(request_id, status)
        if operation == "question":
            return make_file_question_result(request_id, status)
        return make_search_result(request_id, status)
