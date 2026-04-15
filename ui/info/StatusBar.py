from PyQt6.QtWidgets import QStatusBar, QLabel

class StatusBar(QStatusBar):
    """Custom status bar for displaying messages"""
    def __init__(self, parent=None, name:str=""):
        super().__init__(parent)
        self.name_label = QLabel(name)
        self.addPermanentWidget(self.name_label)
        self.status_label = QLabel("")
        self.addWidget(self.status_label)
    
    def update_name(self, name: str):
        self.name_label.setText(name)
    
    def update_status(self, status: str):
        self.status_label.setText(status)