from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QMenu, QMessageBox, QInputDialog,
)

from app_logic.user.ds.Recording import Recording


class RecordingTree(QWidget):
    """
    Left-side panel showing recordings for the currently loaded MIDI.
    Uses QTreeWidget for simplicity.

    String-only design:
      - Each recording item stores its name (str) in UserRole.
      - Signals emit names (str).
    """
    selected = pyqtSignal(object)          # emits str | None
    create_rec = pyqtSignal(str)           # new recording name
    rename_rec = pyqtSignal(str, str)      # old_name, new_name
    delete_rec = pyqtSignal(str)           # name

    def __init__(self, recordings: dict[str, Recording], parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.MIDI_ROOT: QTreeWidgetItem | None = None
        self.recordings = recordings  # reference to the parent recordings dict

        # the tree itself
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        layout.addWidget(self.tree)

        self._suppress_item_changed = False  # helper variable to prevent rename loops

        # set min/max widths of the widget holding the tree
        self.setMinimumWidth(180)
        self.setMaximumWidth(320)

    def init_signals(self):
        """initialize all the signals for
            - right click: open context menu
            - selection: emit selected recording name
            - rename: 
        """
        # right click (context menu)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._open_context_menu)
        # selection
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemChanged.connect(self._on_item_changed)
        # renaming
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.setEditTriggers(
            self.tree.EditTrigger.EditKeyPressed |
            self.tree.EditTrigger.SelectedClicked
        )

    # ---------- Public API ----------
    def set_midi_context(self, midi_display_name: str):
        """Reset tree for a new MIDI file with the given display name."""
        self.tree.clear() # clear any existing items
        self.MIDI_ROOT = QTreeWidgetItem([midi_display_name])

        # root: not editable, just a label/container
        flags = self.MIDI_ROOT.flags()
        self.MIDI_ROOT.setFlags(flags & ~Qt.ItemFlag.ItemIsSelectable)
        self.tree.addTopLevelItem(self.MIDI_ROOT)
        self.MIDI_ROOT.setExpanded(True)

    def set_recordings(self, recordings: list[str]):
        """Replace all recordings under the current MIDI root."""
        if self.MIDI_ROOT is None:
            self.set_midi_context("MIDI")

        self.MIDI_ROOT.takeChildren()  # clear children

        for name in recordings:
            self._add_item(name)

        self.MIDI_ROOT.setExpanded(True)

    def add_recording(self, name: str, select: bool = True):
        """Add one recording item under root."""
        if self.MIDI_ROOT is None:
            self.set_midi_context("MIDI")

        item = self._add_item(name)

        if select:
            self.tree.setCurrentItem(item)

    def revert_item_name(self, old_name: str):
        """
        Call this from TuneBuddy if rename was rejected.
        Reverts the currently edited item's label back to old_name.
        """
        item = self._selected_recording_item()
        if item is None:
            return
        self._suppress_item_changed = True
        item.setText(0, old_name)
        item.setData(0, Qt.ItemDataRole.UserRole, old_name)
        self._suppress_item_changed = False

    def remove_item_by_name(self, name: str):
        """Call this from TuneBuddy after deletion is confirmed/applied."""
        if self.MIDI_ROOT is None:
            return
        for i in range(self.MIDI_ROOT.childCount()):
            child = self.MIDI_ROOT.child(i)
            stored = child.data(0, Qt.ItemDataRole.UserRole)
            if stored == name:
                self.MIDI_ROOT.removeChild(child)
                break

    # ---------- Internal helpers ----------
    def _add_item(self, name: str) -> QTreeWidgetItem:
        """Create and add a recording child item storing `name` as UserRole."""
        item = QTreeWidgetItem([name])
        item.setData(0, Qt.ItemDataRole.UserRole, name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.MIDI_ROOT.addChild(item)
        return item

    def _selected_recording_item(self) -> QTreeWidgetItem | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        item = items[0]
        if item is self.MIDI_ROOT:
            return None
        return item

    def _selected_name(self) -> str | None:
        item = self._selected_recording_item()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    # ---------- UI handlers ----------
    def _on_selection_changed(self):
        name = self._selected_name()
        self.selected.emit(name)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, col: int):
        # double click: start rename
        if item is not None and item is not self.MIDI_ROOT:
            self.tree.editItem(item, 0)

    def _open_context_menu(self, pos: QPoint):
        """Open context menu with create, rename, delete actions."""
        menu = QMenu(self)
        new_action = menu.addAction("New Recording…")

        item = self._selected_recording_item()
        if item is None:
            rename_action = None
            delete_action = None
        else:
            rename_action = menu.addAction("Rename")
            delete_action = menu.addAction("Delete")

        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action == new_action:
            self._prompt_new_recording()
            return

        if item is None:
            return

        if rename_action is not None and action == rename_action:
            self.tree.editItem(item, 0)
            return

        if delete_action is not None and action == delete_action:
            name = item.data(0, Qt.ItemDataRole.UserRole)
            if not name:
                return
            ok = QMessageBox.question(
                self,
                "Delete recording",
                f"Delete recording: {item.text(0)}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ok == QMessageBox.StandardButton.Yes:
                self.delete_rec.emit(name)

    def _prompt_new_recording(self):
        """Open the 'new recording' dialog."""
        name, ok = QInputDialog.getText(self, "New Recording", "Recording name:")
        name = (name or "").strip()
        if ok and name:
            self.create_rec.emit(name)

    def _on_item_changed(self, item: QTreeWidgetItem, col: int):
        """
        Called after editing the item text.
        Treat as rename request and let TuneBuddy validate/apply.
        """
        if self._suppress_item_changed or item is None or item is self.MIDI_ROOT:
            return

        old_name = item.data(0, Qt.ItemDataRole.UserRole)
        new_name = (item.text(0) or "").strip()

        # If old_name isn't set for some reason, initialize it and bail
        if not old_name:
            item.setData(0, Qt.ItemDataRole.UserRole, new_name)
            return

        # Empty rename: revert immediately to old name
        if not new_name:
            self._suppress_item_changed = True
            item.setText(0, old_name)
            self._suppress_item_changed = False
            return

        # No-op rename
        if new_name == old_name:
            return

        # Don't update UserRole yet; parent will accept/reject rename.
        # If accepted, parent should update its dict, then call apply_item_name(...)
        self.rename_rec.emit(old_name, new_name)

    # Optional helper: call this from TuneBuddy after accepting rename
    def apply_item_name(self, old_name: str, new_name: str):
        """Update the currently selected item (or item matching old_name) to new_name."""
        if self.MIDI_ROOT is None:
            return

        # Prefer selected item if it matches old_name
        item = self._selected_recording_item()
        if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == old_name:
            self._suppress_item_changed = True
            item.setText(0, new_name)
            item.setData(0, Qt.ItemDataRole.UserRole, new_name)
            self._suppress_item_changed = False
            return

        # Otherwise search
        for i in range(self.MIDI_ROOT.childCount()):
            child = self.MIDI_ROOT.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) == old_name:
                self._suppress_item_changed = True
                child.setText(0, new_name)
                child.setData(0, Qt.ItemDataRole.UserRole, new_name)
                self._suppress_item_changed = False
                break
