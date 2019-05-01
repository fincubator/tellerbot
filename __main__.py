from asyncio import get_event_loop, Task, CancelledError

from src.app import main


if __name__ == "__main__":
    main()
    print()

    loop = get_event_loop()
    tasks = Task.all_tasks()
    for task in tasks:
        task.cancel()
        try:
            loop.run_until_complete(task)
        except CancelledError:
            pass
