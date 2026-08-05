from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from bitcoin_bot.strategy_loader import AVAILABLE_STRATEGIES


ROOT = Path(__file__).resolve().parent


class BotLauncher(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Bots Trading · Selector")
        self.setFixedSize(560, 420)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(36, 32, 36, 32)
        layout.setSpacing(14)
        title = QLabel("BOTS TRADING")
        title.setObjectName("title")
        subtitle = QLabel(
            "Elige qué estrategia quieres simular. Las dos pueden ejecutarse "
            "a la vez con saldo, configuración e historial independientes."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        for strategy_id, description in AVAILABLE_STRATEGIES.items():
            button = QPushButton(f"Abrir {strategy_id}\n{description}")
            button.clicked.connect(lambda checked=False, value=strategy_id: self.open_bot(value))
            layout.addWidget(button)
        both = QPushButton("Abrir los dos bots simultáneamente")
        both.setObjectName("both")
        both.clicked.connect(self.open_all)
        layout.addWidget(both)
        layout.addStretch()
        note = QLabel("Simulación local: nunca envía órdenes reales.")
        note.setAlignment(Qt.AlignCenter)
        layout.addWidget(note)
        self.setCentralWidget(panel)
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #071426; color: #e5edf8; }
            QLabel#title { color: #fbbf24; font-size: 28px; font-weight: 900; }
            QPushButton { min-height: 58px; border: 1px solid #28405e;
              border-radius: 10px; background: #10243c; color: white;
              font-size: 14px; font-weight: 700; text-align: left; padding: 8px 18px; }
            QPushButton:hover { background: #173451; border-color: #4c78a8; }
            QPushButton#both { border-left: 5px solid #f59e0b; }
            """
        )

    def open_bot(self, strategy_id: str) -> None:
        environment = os.environ.copy()
        environment["BOT_STRATEGY"] = strategy_id
        subprocess.Popen([sys.executable, "-m", "bitcoin_bot"], cwd=ROOT, env=environment)

    def open_all(self) -> None:
        for strategy_id in AVAILABLE_STRATEGIES:
            self.open_bot(strategy_id)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Bots Trading Launcher")
    app.setOrganizationName("Santiago")
    window = BotLauncher()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
