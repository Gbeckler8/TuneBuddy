from bisect import bisect_left, bisect_right
import numpy as np
from app_logic.NoteData import Note

class Mistake:
    def __init__(self, type: str, user_note: Note, midi_note: Note):
        self.type = type
        self.user_note = user_note
        self.midi_note = midi_note

class Alignment:
    def __init__(self, notes: list[tuple[Note, Note]], mistakes: list[Mistake]):
        # these are crucial
        self.pairs: list[tuple[Note, Note]] = notes
        self.mistakes: list[Mistake] = mistakes # ??? might not be super "crucial" lol
        
        # our time-indexable {t: (n,m)} dictionary
        # is there any way to make each just store a reference or smth?...
        self.init_2(notes)
        self.THRESH = 1 # same as StringEditor.TOLERANCE

    def init_2(self, pairs):
        """initialize the two pairs dictionaries for faster time indexing
        in self.get_alignment"""
        self.pairs_1 = {}
        self.pairs_2 = {}

        for n, m in pairs: # go through and dissect the pairs
            if n is None and m is None:
                continue
            if n is None:
                tmin = m.start_time
                tmax = m.end_time
            elif m is None:
                tmin = n.start_time
                tmax = n.end_time
            else:
                tmin = min(n.start_time, m.start_time)
                tmax = max(n.end_time, m.end_time)
            
            self.pairs_1[tmin] = (n, m)
            self.pairs_2[tmax] = (n, m)

        self.times_1 = list(self.pairs_1.keys())
        self.times_2 = list(self.pairs_2.keys())

        # print(f"Initialized with\npairs1\n---\n{self.pairs_1}\npairs2\n---\n{self.pairs_2}")

    def get_alignment(self, t_min: float, t_max: float) -> tuple[list[tuple[Note, Note]], 
                                                                 list[tuple[Note, Note]], 
                                                                 list[Note], list[Note]]:
        """returns all note pairs found within the time boundaries
        
        Args:
            t_min (float): minimum time (sec)
            t_max (float): maximum time (sec)
        
        Returns:
            tuple: (goods, subs, ins, dels)
        """
        i = bisect_left(self.times_1, t_min) # yes good
        j = bisect_right(self.times_2, t_max)

        pairs = self.pairs[i:j]
        ins, dels, subs, goods, = [], [], [], []
        for n, m in pairs:
            if n and not m: # insertion
                ins.append(n)
            elif not n and m: # deletion
                dels.append(m)
            elif abs(n.midi_num[0]-m.midi_num[0]) > self.THRESH:
                subs.append((n, m)) # substitution
            else: # good
                goods.append((n, m))

        # print(f"alignment @ {t_min}:\n---\n"
        #     f"goods: {goods},\n"
        #     f"subs: {subs},\n"
        #     f"ins: {ins},\n"
        #     f"dels: {dels}"
        # )

        # the end
        return goods, subs, ins, dels