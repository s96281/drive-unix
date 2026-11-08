import { create } from 'zustand';
import type { ActivityEvent } from '../api/types';

interface ActivityState {
  events: ActivityEvent[];
  isPaused: boolean;
  filter: 'all' | 'tasks' | 'logs';
  addEvent: (event: Omit<ActivityEvent, 'id'>) => void;
  clear: () => void;
  togglePause: () => void;
  setFilter: (filter: 'all' | 'tasks' | 'logs') => void;
}

let eventCounter = 0;

export const useActivityStore = create<ActivityState>((set) => ({
  events: [],
  isPaused: false,
  filter: 'all',
  addEvent: (event) =>
    set((state) => {
      if (state.isPaused) return state;
      const newEvent: ActivityEvent = {
        ...event,
        id: `ev-${Date.now()}-${++eventCounter}`,
      };
      // Keep up to 250 recent events
      const updated = [newEvent, ...state.events].slice(0, 250);
      return { events: updated };
    }),
  clear: () => set({ events: [] }),
  togglePause: () => set((state) => ({ isPaused: !state.isPaused })),
  setFilter: (filter) => set({ filter }),
}));
