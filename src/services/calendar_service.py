class CalendarService:
    def __init__(self):

        self.busy_slots = ["09:00", "14:00"]

    def check_availability(self, date_str):
        """
        Simulates checking Google Calendar for free slots.
        Returns a list of available hours for the next 24h.
        """

        print(f"Checking calendar availability for {date_str}...")

        all_slots = ["09:00", "10:00", "11:00", "13:00", "14:00", "15:00"]
        free_slots = [slot for slot in all_slots if slot not in self.busy_slots]

        return free_slots

    def book_slot(self, date_str, time_slot, task_description):
        """
        Simulates booking a slot.
        """
        if time_slot in self.busy_slots:
            return f"Error: Slot {time_slot} is already taken."

        self.busy_slots.append(time_slot)
        return f"Scheduled: '{task_description}' on {date_str} at {time_slot}."
