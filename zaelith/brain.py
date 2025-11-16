import textwrap
from detector import analyze_response


def _read_block(prompt: str) -> str:
    """Read multi-line input, handling paste properly.
    
    Buffers all pasted lines, shows them back, waits for confirmation.
    This prevents each line from being processed separately when pasting.
    """
    import sys
    
    print(prompt)
    print("(Paste your multi-line text, then type 'DONE' on a new line and press Enter)")
    print("-" * 60)
    
    lines = []
    print("Paste your text (multi-line supported):")
    
    # Read lines until user types 'DONE'
    while True:
        try:
            line = input()
            # Check for completion marker
            if line.strip().upper() == "DONE":
                break
            lines.append(line)
        except (EOFError, KeyboardInterrupt):
            # Ctrl+D or Ctrl+C - finish input
            break
    
    # Join all lines into single text block
    text_block = "\n".join(lines)
    
    # Show back to user for confirmation
    print("\n" + "=" * 60)
    print("You entered:")
    print("-" * 60)
    print(text_block)
    print("-" * 60)
    print("\nPress Enter to confirm, or type 'EDIT' to re-enter:")
    
    # Wait for confirmation
    confirmation = input().strip().upper()
    if confirmation == "EDIT":
        # Recursive call to re-enter
        return _read_block(prompt)
    
    return text_block


def _print_report(report: dict) -> None:
    print("\n=== Lie Detector Report ===")
    for criterion, details in report.items():
        if criterion == "summary_grade":
            continue
        status = "TRIGGERED" if details["triggered"] else "--"
        print(f"[{criterion.upper()}] {status}")
        for ev in details.get("evidence", []):
            print(textwrap.fill(f"- {ev}", subsequent_indent="  "))
    print("=== Summary ===")
    print(report["summary_grade"])


def main() -> None:
    import sys
    import os
    prompt_file = None
    response_file = None
    # Parse CLI args for --prompt-file and --response-file
    for i, arg in enumerate(sys.argv):
        if arg == "--prompt-file" and i + 1 < len(sys.argv):
            prompt_file = sys.argv[i + 1]
        if arg == "--response-file" and i + 1 < len(sys.argv):
            response_file = sys.argv[i + 1]

    if prompt_file and os.path.isfile(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as f:
            user_prompt = f.read().rstrip("\n")
    else:
        user_prompt = _read_block("Enter the original prompt given to the LLM:")

    if response_file and os.path.isfile(response_file):
        with open(response_file, "r", encoding="utf-8") as f:
            llm_response = f.read().rstrip("\n")
    else:
        llm_response = _read_block("Enter the full response from the LLM:")

    print("\nYou entered the following prompt:")
    print(user_prompt)
    print("\nYou entered the following response:")
    print(llm_response)
    # Interactive loop: let the user decide when to run, edit, or quit
    while True:
        print("\nType one of: 'run' to run the detector, 'edit prompt', 'edit response', or 'quit'")
        choice = input("Command: ").strip().lower()
        if choice == "run":
            report = analyze_response(user_prompt, llm_response)
            # Debug: show raw report structure so evidence lists and flags are visible
            print("\nDEBUG: raw report dict:")
            print(report)
            _print_report(report)
        elif choice == "edit prompt":
            user_prompt = _read_block("Edit the original prompt (finish with two empty lines)")
            print("Updated prompt:")
            print(user_prompt)
        elif choice == "edit response":
            llm_response = _read_block("Edit the full response (finish with two empty lines)")
            print("Updated response:")
            print(llm_response)
        elif choice == "quit":
            print("Exiting.")
            break
        else:
            print("Unknown command. Please enter 'run', 'edit prompt', 'edit response', or 'quit'.")


if __name__ == "__main__":
    main()
