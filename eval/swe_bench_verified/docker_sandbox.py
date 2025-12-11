from typing import Optional
import subprocess


EPOCH_IMAGE_PREFIX = "ghcr.io/epoch-research/swe-bench.eval.x86_64"
CONTAINER_WORKSPACE = "/testbed"


class DockerSandbox:
    """Manages Docker container lifecycle for SWE-Bench evaluation."""

    def __init__(self, container_name: str, instance_id: str):
        """
        Initialize the Docker sandbox.

        Args:
            container_name: Name for the Docker container
            instance_id: SWE-Bench instance ID (e.g., 'astropy__astropy-7671')
        """
        self.container_name = container_name
        self.instance_id = instance_id
        self.image = f"{EPOCH_IMAGE_PREFIX}.{instance_id}"
        self.container_id: Optional[str] = None

    def start(self) -> str:
        # Remove existing container with same name if exists
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            capture_output=True,
            check=False,
        )

        # Start new container
        result = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--platform",
                "linux/amd64",
                "--name",
                self.container_name,
                "-w",
                CONTAINER_WORKSPACE,
                self.image,
                "tail",
                "-f",
                "/dev/null",  # Keep container running
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.container_id = result.stdout.strip()
        print(
            f"[DockerSandbox] Started container: {self.container_name} ({self.container_id[:12]})"
        )
        print(f"[DockerSandbox] Using image: {self.image}")

        self.exec(
            f"""
            cd {CONTAINER_WORKSPACE} && \
            rm -rf .git && \
            git init && \
            git add -A && \
            git commit -m "initial" --allow-empty
            """,
        )
        print("[DockerSandbox] Container ready")

        return self.container_id

    def exec(
        self, command: str, workdir: Optional[str] = None
    ) -> subprocess.CompletedProcess:
        """Execute a command inside the container."""
        cmd = ["docker", "exec"]
        if workdir:
            cmd.extend(["-w", workdir])
        cmd.extend([self.container_name, "bash", "-c", command])
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    def stop(self):
        """Stop and remove the container."""
        if self.container_name:
            subprocess.run(
                ["docker", "rm", "-f", self.container_name],
                capture_output=True,
                check=False,
            )
            print(f"[DockerSandbox] Stopped container: {self.container_name}")
