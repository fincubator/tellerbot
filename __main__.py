from asyncio import all_tasks
from asyncio import CancelledError
from asyncio import get_event_loop

from src.app import main


if __name__ == '__main__':
    main()
    print()

    loop = get_event_loop()
    for task in all_tasks(loop):
        task.cancel()
        try:
            loop.run_until_complete(task)
        except CancelledError:
            pass
