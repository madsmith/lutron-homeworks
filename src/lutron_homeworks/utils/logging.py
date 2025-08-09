import logging

class LevelColorFormatter(logging.Formatter):
    RED = "\033[31m"
    GREEN = "\033[32m"
    RESET = "\033[0m"

    LEVEL_COLORS = {
        logging.ERROR: RED,
        logging.CRITICAL: RED,
        logging.WARNING: RED,
        logging.INFO: GREEN,
        logging.DEBUG: GREEN,
    }

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, "")
        levelname = record.levelname
        if color:
            levelname = f"{color}{levelname}{self.RESET}"
        record.levelname = levelname
        return super().format(record)