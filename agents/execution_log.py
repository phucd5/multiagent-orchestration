from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from datetime import datetime
import json
import os

# pylint: disable=import-error
from rich.console import Console
from rich.panel import Panel

PRINT_SYS_PROMPT = True


@dataclass
class ToolUseEntry:
    """Represents a single tool use action."""

    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[str] = None
    is_error: bool = False


@dataclass
class BlockEntry:
    """Represents a single block in the conversation."""

    block_number: int
    agent_id: str = "agent"
    assistant_message: Optional[str] = None
    tool_uses: List[ToolUseEntry] = field(default_factory=list)


@dataclass
class ExecutionStats:
    """Summary statistics for the execution."""

    num_turns: int
    duration_ms: int
    duration_api_ms: int
    total_cost_usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


class ExecutionLog:
    """
    Captures tool uses, assistant messages, and execution statistics.
    """

    def __init__(self, debug: bool = False):
        self.blocks: List[BlockEntry] = []
        self.stats: Optional[ExecutionStats] = None
        self.agent_stats: Dict[str, ExecutionStats] = {}  # Per-agent stats
        self.start_time: datetime = datetime.now()
        self.debug = debug
        self._current_block: Optional[BlockEntry] = None
        self._block_counter: int = 0
        self._console = Console() if debug else None
        self._debug_content: List[str] = []
        self.system_prompt: Optional[str] = None
        self.user_query: Optional[str] = None

    def has_active_turn(self) -> bool:
        """Check if there is an active block."""
        return self._current_block is not None

    def set_system_prompt(self, system_prompt: str):
        """Set the system prompt used for this execution."""
        self.system_prompt = system_prompt
        if PRINT_SYS_PROMPT and self.debug and self._console:
            panel = Panel(
                system_prompt,
                title="[bold]📋 System Prompt[/bold]",
                border_style="cyan",
                expand=False,
            )
            self._console.print(panel)
            self._console.print()

    def set_user_query(self, user_query: str):
        """Set the user query/task for this execution."""
        self.user_query = user_query
        if self.debug and self._console:
            panel = Panel(
                user_query,
                title="[bold]❓ User Query[/bold]",
                border_style="yellow",
                expand=False,
            )
            self._console.print(panel)
            self._console.print()

    def start_turn(self, agent_id: str):
        """Start a new block for the specified agent."""
        self._block_counter += 1
        self._current_block = BlockEntry(
            block_number=self._block_counter, agent_id=agent_id
        )
        if self.debug:
            self._debug_content = []

    def add_assistant_message(self, message: str):
        """Add assistant message to current block."""
        if self._current_block is None:
            raise ValueError(
                "No active block. Call start_turn(agent_id) before adding messages."
            )

        if self._current_block.assistant_message:
            self._current_block.assistant_message += "\n" + message
        else:
            self._current_block.assistant_message = message

        if self.debug:
            self._debug_content.append(f"[bold]💬 Text:[/bold] {message}")

    def add_tool_use(self, tool_name: str, arguments: Dict[str, Any]):
        """Add tool use to current block."""
        if self._current_block is None:
            raise ValueError(
                "No active block. Call start_turn(agent_id) before adding tool uses."
            )

        tool_entry = ToolUseEntry(tool_name=tool_name, arguments=arguments)
        self._current_block.tool_uses.append(tool_entry)

        if self.debug:
            self._debug_content.append(f"[bold blue]🔧 Tool:[/bold blue] {tool_name}")
            if arguments:
                for key, value in arguments.items():
                    self._debug_content.append(f"[blue]{key}:[/blue] {value}")

    def add_tool_result(self, result: str, is_error: bool = False):
        """Add a result to the most recent tool use."""
        if self._current_block and self._current_block.tool_uses:
            self._current_block.tool_uses[-1].result = result
            self._current_block.tool_uses[-1].is_error = is_error

            if self.debug:
                if is_error:
                    self._debug_content.append(f"[red]❌ ERROR:[/red] {result}")
                else:
                    self._debug_content.append(f"[green]✅ Result:[/green] {result}")

    def end_turn(self):
        """End the current block and add it to the log."""
        if self._current_block:
            if self.debug and self._console:
                # Only print if there's actual content
                if self._debug_content:
                    content = "\n".join(self._debug_content)
                    panel = Panel(
                        content,
                        title=f"[bold]Block {self._current_block.block_number} - 🤖 {self._current_block.agent_id}[/bold]",
                        border_style="green",
                        expand=False,
                    )
                    self._console.print(panel)
                    self._console.print()
                self._debug_content = []

            self.blocks.append(self._current_block)
            self._current_block = None

    def set_stats(
        self,
        num_turns: int,
        duration_ms: int,
        duration_api_ms: int,
        total_cost_usd: float,
        agent_id: Optional[str] = None,
    ):
        """Set execution statistics for an agent or overall."""
        stats = ExecutionStats(
            num_turns=num_turns,
            duration_ms=duration_ms,
            duration_api_ms=duration_api_ms,
            total_cost_usd=total_cost_usd,
        )

        if agent_id:
            self.agent_stats[agent_id] = stats
        else:
            self.stats = stats

    def print_rich(self):
        """Print the execution log with rich colored boxes."""
        console = Console()
        console.print("=" * 80, style="cyan")
        console.print("EXECUTION LOG", style="cyan bold")
        console.print("=" * 80, style="cyan")
        console.print(
            f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}", style="yellow"
        )
        console.print()

        # Print system prompt if available
        if PRINT_SYS_PROMPT and self.system_prompt:
            panel = Panel(
                self.system_prompt,
                title="[bold]📋 System Prompt[/bold]",
                border_style="cyan",
                expand=False,
            )
            console.print(panel)
            console.print()

        # Print user query if available
        if self.user_query:
            panel = Panel(
                self.user_query,
                title="[bold]❓ User Query[/bold]",
                border_style="yellow",
                expand=False,
            )
            console.print(panel)
            console.print()

        for block in self.blocks:
            self._print_block_rich(console, block)

        if self.stats:
            console.print("=" * 80, style="cyan")
            console.print("EXECUTION STATISTICS", style="cyan bold")
            console.print("=" * 80, style="cyan")
            console.print(f"[yellow]Total Turns:[/yellow] {self.stats.num_turns}")
            console.print(
                f"[yellow]Duration:[/yellow] {self.stats.duration_ms}ms (API: {self.stats.duration_api_ms}ms)"
            )
            console.print(
                f"[yellow]Tokens:[/yellow] Input: {self.stats.input_tokens}, Output: {self.stats.output_tokens}, Cache Read: {self.stats.cache_read_tokens}"
            )
            console.print("=" * 80, style="cyan")

    def summary(self):
        """Print a brief summary of the execution with a colored box."""
        console = Console()

        if not self.stats and not self.agent_stats:
            content = "Execution completed (no statistics available)"
        else:
            content_lines = []

            # Calculate totals
            total_turns = 0
            total_cost = 0.0
            total_duration_ms = 0
            total_duration_api_ms = 0

            if self.stats:
                total_turns += self.stats.num_turns
                total_cost += self.stats.total_cost_usd
                total_duration_ms = (
                    self.stats.duration_ms
                )  # Leader duration is the overall duration
                total_duration_api_ms = self.stats.duration_api_ms

            if self.agent_stats:
                for stats in self.agent_stats.values():
                    total_turns += stats.num_turns
                    total_cost += stats.total_cost_usd

            # Overall stats
            if self.stats or self.agent_stats:
                content_lines.append("[bold green]OVERALL[/bold green]")
                content_lines.append(
                    f"[yellow]Total Turns:[/yellow] {total_turns}\n"
                    f"[yellow]Total Duration:[/yellow] {total_duration_ms}ms (API: {total_duration_api_ms}ms)\n"
                    f"[yellow]Total Cost:[/yellow] ${total_cost:.4f}"
                )
                content_lines.append("")

            # Leader stats
            if self.stats:
                content_lines.append("[bold cyan]LEADER[/bold cyan]")
                content_lines.append(
                    f"[yellow]Turns:[/yellow] {self.stats.num_turns}\n"
                    f"[yellow]Duration:[/yellow] {self.stats.duration_ms}ms (API: {self.stats.duration_api_ms}ms)\n"
                    f"[yellow]Cost:[/yellow] ${self.stats.total_cost_usd:.4f}"
                )

            # Per-agent stats
            if self.agent_stats:
                for agent_id, stats in self.agent_stats.items():
                    content_lines.append("")
                    content_lines.append(f"[bold cyan]{agent_id.upper()}[/bold cyan]")
                    content_lines.append(
                        f"[yellow]Turns:[/yellow] {stats.num_turns}\n"
                        f"[yellow]Duration:[/yellow] {stats.duration_ms}ms (API: {stats.duration_api_ms}ms)\n"
                        f"[yellow]Cost:[/yellow] ${stats.total_cost_usd:.4f}"
                    )

            content = "\n".join(content_lines)

        panel = Panel(
            content,
            title="[bold]📊 Execution Summary[/bold]",
            border_style="cyan",
            expand=False,
        )
        console.print(panel)

    def _print_block_rich(self, console: Console, block: BlockEntry):
        content_lines = []

        if block.assistant_message:
            content_lines.append(f"[bold]💬 Text:[/bold] {block.assistant_message}")

        for tool_use in block.tool_uses:
            content_lines.append(
                f"[bold blue]🔧 Tool:[/bold blue] {tool_use.tool_name}"
            )

            if tool_use.arguments:
                for key, value in tool_use.arguments.items():
                    content_lines.append(f"[blue]{key}:[/blue] {value}")

            if tool_use.result:
                if tool_use.is_error:
                    content_lines.append(f"[red]❌ ERROR:[/red] {tool_use.result}")
                else:
                    content_lines.append(f"[green]✅ Result:[/green] {tool_use.result}")

        panel = Panel(
            "\n".join(content_lines),
            title=f"[bold]Block {block.block_number} - 🤖 {block.agent_id}[/bold]",
            border_style="green",
            expand=False,
        )

        console.print(panel)
        console.print()

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the execution log to a dictionary for JSON serialization.

        Returns:
            Dictionary containing all execution log data
        """
        # Convert blocks to dictionaries
        blocks_data = []
        for block in self.blocks:
            block_dict = {
                "block_number": block.block_number,
                "agent_id": block.agent_id,
                "assistant_message": block.assistant_message,
                "tool_uses": [],
            }

            for tool_use in block.tool_uses:
                tool_dict = {
                    "tool_name": tool_use.tool_name,
                    "arguments": tool_use.arguments,
                    "result": tool_use.result,
                    "is_error": tool_use.is_error,
                }
                block_dict["tool_uses"].append(tool_dict)

            blocks_data.append(block_dict)

        # Build the main log dictionary
        log_data = {
            "start_time": self.start_time.isoformat(),
            "system_prompt": self.system_prompt,
            "user_query": self.user_query,
            "blocks": blocks_data,
            "stats": None,
            "agent_stats": {},
        }

        # Add overall stats if available
        if self.stats:
            log_data["stats"] = {
                "num_turns": self.stats.num_turns,
                "duration_ms": self.stats.duration_ms,
                "duration_api_ms": self.stats.duration_api_ms,
                "total_cost_usd": self.stats.total_cost_usd,
                "input_tokens": self.stats.input_tokens,
                "output_tokens": self.stats.output_tokens,
                "cache_read_tokens": self.stats.cache_read_tokens,
            }

        # Add per-agent stats if available
        for agent_id, stats in self.agent_stats.items():
            log_data["agent_stats"][agent_id] = {
                "num_turns": stats.num_turns,
                "duration_ms": stats.duration_ms,
                "duration_api_ms": stats.duration_api_ms,
                "total_cost_usd": stats.total_cost_usd,
                "input_tokens": stats.input_tokens,
                "output_tokens": stats.output_tokens,
                "cache_read_tokens": stats.cache_read_tokens,
            }

        # Calculate overall summary
        total_turns = 0
        total_cost = 0.0
        total_duration_ms = 0
        total_duration_api_ms = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read_tokens = 0

        if self.stats:
            total_turns += self.stats.num_turns
            total_cost += self.stats.total_cost_usd
            total_duration_ms = self.stats.duration_ms
            total_duration_api_ms = self.stats.duration_api_ms
            total_input_tokens += self.stats.input_tokens
            total_output_tokens += self.stats.output_tokens
            total_cache_read_tokens += self.stats.cache_read_tokens

        if self.agent_stats:
            for stats in self.agent_stats.values():
                total_turns += stats.num_turns
                total_cost += stats.total_cost_usd
                total_input_tokens += stats.input_tokens
                total_output_tokens += stats.output_tokens
                total_cache_read_tokens += stats.cache_read_tokens

        log_data["summary"] = {
            "total_turns": total_turns,
            "total_cost_usd": total_cost,
            "total_duration_ms": total_duration_ms,
            "total_duration_api_ms": total_duration_api_ms,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cache_read_tokens": total_cache_read_tokens,
        }

        return log_data

    def save(
        self,
        log_directory: str,
        task_id: str,
        log_filename: str = "execution_logs.json",
    ):
        """
        Save the execution log to a JSON file in the specified directory.
        Appends to the file if it already exists, storing logs as a dictionary indexed by task_id.

        Args:
            log_directory: Directory where the log should be saved
            task_id: Task identifier to index this log entry
            log_filename: Name of the log file (default: execution_logs.json)
        """
        os.makedirs(log_directory, exist_ok=True)

        log_path = os.path.join(log_directory, log_filename)

        # Load existing logs if the file exists
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                try:
                    all_logs = json.load(f)
                except json.JSONDecodeError:
                    # If file is corrupted, start fresh
                    all_logs = {}
        else:
            all_logs = {}

        # Convert current log to dictionary
        log_data = self.to_dict()

        # Add/update the log for this task_id
        all_logs[task_id] = log_data

        # Write all logs back to the file with pretty formatting
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(all_logs, f, indent=2, ensure_ascii=False)

        return log_path
