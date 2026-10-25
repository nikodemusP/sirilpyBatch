from collections.abc import Callable

cmd_to_output = Callable[[str], None]

def set_batch_command_output(cmd: Callable[..., None]):
    """
    Set the function that will be called with each command string before it is executed.

    This is useful for logging or debugging purposes, as it allows you to see the exact commands
    that are being sent to Siril before they are run.
    """
    global cmd_to_output
    cmd_to_output = cmd

class BatchCmd:
    def __init__(self):
        self.args = []

    def append(self, *args):
        if args:
            self.args.extend(args)
        return self

    def add_arg(self, template, *values):
        """
        Format `template` with one or more values and append it as one arg.

        Supports:
        add_arg("-bias={}", value)              # single value
        add_arg("-catalog={},{}", low, high)     # multiple positional values
        add_arg("-catalog={},{}", (low, high))   # single tuple/list, unpacked
        """
        if not values:
            return self
        # unwrap a single tuple/list argument into multiple values
        if len(values) == 1 and isinstance(values[0], (tuple, list)):
            values = tuple(values[0])

        if any(v is None for v in values):
            return self

        self.args.append(f'"{template.format(*values)}"')
        return self

    def add_opt(self, option, condition):
        if condition:
            self.args.append(option)
        return self

    def run(self):
        return cmd_to_output(*self.args)

    def __iter__(self):
        return iter(self.args)