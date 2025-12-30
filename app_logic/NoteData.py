import numpy as np
from collections import defaultdict
from bisect import bisect_left, bisect_right
class Note:
    def __init__(self, i: int, start_time: float, end_time: float, midi_num: list[float]):
        self.id = i # used to keep track of note within the piece
        self.start_time = start_time
        self.end_time = end_time
        self.midi_num = midi_num

class NoteData:
    """Data to store and retrieve notes efficiently (indexing + binary search)
    Supports read by index and by start/end time."""
    def __init__(self):
        self.data: dict[float, Note] = defaultdict(Note)
        self.times: list[float] = [] # times are stored for binary search 

    def write_note(self, note: Note):
        """writes a single note to the note data @ the corresponding start_time"""
        if note.start_time not in self.data:
            # keep times sorted for binary search
            i = bisect_left(self.times, note.start_time)
            self.times.insert(i, note.start_time)
        
        self.data[note.start_time] = note

    def get_length(self) -> float:
        """return the length of the note data in seconds"""
        if not self.times:
            return 0.0
        last_time = self.times[-1]
        last_note = self.data[last_time]
        return last_note.end_time
    
    def get_bounds(self) -> tuple[float, float]:
        """return the (start_time, end_time) bounds of the note data"""
        if not self.times:
            return (0.0, 0.0)
        first_time = self.times[0]
        last_time = self.get_length()
        return (first_time, last_time)

    def get_minimum_note_length(self) -> float:
        """return the minimum note length in seconds"""
        if not self.times:
            return 0.0
        
        min_length = float('inf')
        for t in self.times:
            n = self.data[t]
            note_length = n.end_time - n.start_time
            if note_length < min_length:
                min_length = note_length
        
        return min_length if min_length != float('inf') else -1

    def read(self, start_time: float=None, end_time: float=None, 
             i=None, j=None, clean:bool=False) -> list[Note]:        
        """return all notes found within the start_time - end_time boundaries"""
        if not self.times or (start_time is None and end_time is None and i is None and j is None):
            return []
        
        if i is not None and j is not None:
            return self._read_index(i, j, clean=clean)

        return self._read_time(start_time, end_time, clean=clean)

    def _read_index(self, i: int, j: int, clean: bool=False) -> list[Note]:
        """return all notes found within the note index boundaries i-j"""
        if i < 0 or j > len(self.times) or i >= j:
            return []
        
        notes = []
        for t in self.times[i:j]:
            notes.append(self.data[t])

        if clean:
            notes = [n for n in notes if n.midi_num[0] != -1]
            
        return notes

    def _read_time(self, start_time: float, end_time: float, clean: bool=False) -> list[Note]:
        """return all notes found within the start_time - end_time boundaries"""
        if not self.times or start_time is None or end_time is None:
            return []

        j = bisect_right(self.times, end_time)

        notes = []
        for t in self.times[:j]:
            n = self.data[t]
            # ensure we get notes within the boundaries
            notes.append(n) if n.end_time >= start_time else None

        if clean:
            notes = [n for n in notes if n.midi_num[0] != -1]
            
        return notes

    def read_note(self, start_time: float=None, i: int=None) -> Note:
        """read a single note corresponding to the closest time or the note index i"""
        if not self.times or (start_time is None and i is None):
            return None
        
        if i is not None:
            if i < 0 or i >= len(self.times):
                return None
            return self.data[self.times[i]]
        
        # else, binary search for closest time
        i = bisect_left(self.times, start_time)
        if i == 0:
            closest_time = self.times[0]
        elif i == len(self.times):
            closest_time = self.times[-1]
        else:
            before = self.times[i - 1]
            after = self.times[i]
            closest_time = before if abs(before - start_time) < abs(after - start_time) else after
        return self.data[closest_time]
