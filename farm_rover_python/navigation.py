"""Obstacle avoidance + movement decisions. Arduino executes; Python decides."""
import config

def handle_obstacle(sender, obstacle_cm: int, logger):
    """Returns True if the rover is blocked and had to avoid."""
    if obstacle_cm >= 0 and obstacle_cm < config.OBSTACLE_STOP_CM:
        logger.info(f"Obstacle at {obstacle_cm}cm -> avoiding (turn left)")
        sender.stop()
        sender.turn_left()
        return True
    return False

def resume_patrol(sender):
    sender.forward()
