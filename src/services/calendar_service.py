class CalendarService:
    """A mock service for managing calendar availability and bookings.

    This class simulates a connection to an external calendar API (like Google Calendar).
    It maintains a local list of busy slots and allows checking for availability
    or booking new appointments.
    """
    def __init__(self):

        self.busy_slots = ["09:00", "14:00"]

    def check_availability(self, date_str: str):
            """Simulates checking a calendar for free time slots on a specific date.

            This method generates a list of standard business hours and filters out
            any slots that are currently marked as 'busy' in the internal state.

            Args:
                date_str (str): The date to check for availability (e.g., "2023-10-27").
                    Note: This mock implementation currently ignores the specific date
                    and checks against a global list of busy slots.

            Returns:
                list[str]: A list of available time slots in "HH:MM" format
                (e.g., ["10:00", "11:00"]).
            """
            print(f"Checking calendar availability for {date_str}...")

            all_slots = ["09:00", "10:00", "11:00", "13:00", "14:00", "15:00"]
            free_slots = [slot for slot in all_slots if slot not in self.busy_slots]

            return free_slots

    def book_slot(self, date_str: str, time_slot: str, task_description: str):
        """Simulates booking a specific time slot for a task.

        If the requested slot is available, it is added to the busy list.
        If the slot is already taken, an error message is returned.

        Args:
            date_str (str): The date for the booking.
            time_slot (str): The requested time in "HH:MM" format.
            task_description (str): A brief description of the maintenance task.

        Returns:
            str: A confirmation message if successful, or an error message
            starting with "Error:" if the slot is unavailable.
        """
        if time_slot in self.busy_slots:
            return f"Error: Slot {time_slot} is already taken."

        self.busy_slots.append(time_slot)
        return f"Scheduled: '{task_description}' on {date_str} at {time_slot}."
