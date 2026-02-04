#!/usr/bin/env python
"""Simple script to talk to the JournalAgent."""

import argparse
import importlib.util

from dotenv import load_dotenv
load_dotenv()

# Direct import to bypass agents/__init__.py
spec = importlib.util.spec_from_file_location("agent_journal", "agents/agent_journal.py")
agent_journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_journal)
JournalAgent = agent_journal.JournalAgent
MODELS = agent_journal.MODELS


def print_metadata(agent, show_metadata):
    """Print token usage and response time if enabled."""
    if show_metadata and agent.last_metadata:
        m = agent.last_metadata
        print(f"\n  [{m['model']}] in: {m['input_tokens']} | out: {m['output_tokens']} | time: {m['elapsed_time']:.2f}s")


def get_input():
    """Get user input, return None on quit commands."""
    user_input = input("\nYou: ").strip()
    if not user_input:
        return ""
    if user_input.lower() in ("quit", "exit", "q"):
        return None
    return user_input


def run_finalize(agent, title, show_metadata):
    """Run the finalize phase: emotion check and archive."""
    agent._save_to_archive(agent.final_summary, "summarize")
    print("\n--- Finalizing Journal ---\n")

    response = agent.finalize(title)
    print(f"\n{response}")
    print_metadata(agent, show_metadata)

    # Finalize loop for emotion questions
    while True:
        try:
            user_input = get_input()
            if user_input is None or user_input.lower() == "end":
                print(f"\nJournal '{agent.journal_title}' archived!")
                return
            if not user_input:
                continue

            agent.finalize_receive(user_input)
            response = agent.finalize_reply()
            print(f"\n{response}")
            print_metadata(agent, show_metadata)
        except KeyboardInterrupt:
            return


def run_narrative(agent, show_metadata):
    """Run the narrative therapy phase."""
    while True:
        try:
            user_input = get_input()
            if user_input is None:
                return
            if not user_input:
                continue

            # Summarize triggers finalize flow
            if user_input.lower() == "summarize":
                print("\n--- Reflection Summary ---\n")
                summary = agent.summarize()
                print(summary)
                print_metadata(agent, show_metadata)

                # Get title for finalize
                title = get_input()
                if title is None:
                    return

                run_finalize(agent, title, show_metadata)
                return

            # Normal narrative conversation
            agent.narrative_receive(user_input)
            response = agent.narrative_reply()
            print(f"\n{response}")
            print_metadata(agent, show_metadata)
        except KeyboardInterrupt:
            return


def run_cbt(agent, show_metadata):
    """Run the CBT journaling phase."""
    print(agent.messages[-1]["content"])

    while True:
        try:
            user_input = get_input()
            if user_input is None:
                return
            if not user_input:
                continue

            # Reframe the journal
            if user_input.lower() == "reframe":
                print("\n--- Reframed Journal Entry ---\n")
                reframed = agent.reframe()
                print(reframed)
                print_metadata(agent, show_metadata)
                continue

            # Move to narrative phase
            if user_input.lower() == "next":
                agent._save_to_archive(agent.reframed_journal, "reframe")
                print("\n--- Narrative Therapy Session ---\n")
                response = agent.start_narrative()
                print(f"\n{response}")
                print_metadata(agent, show_metadata)

                run_narrative(agent, show_metadata)
                return

            # Normal CBT conversation
            agent.cbt_receive(user_input)
            response = agent.cbt_reply()
            print(f"\n{response}")
            print_metadata(agent, show_metadata)
        except KeyboardInterrupt:
            return


def main():
    parser = argparse.ArgumentParser(description="Talk to the Journal Agent")
    parser.add_argument("--model", choices=["opus", "sonnet"], default="sonnet",
                        help="Model to use: opus (default) or sonnet")
    parser.add_argument("--show-metadata", action="store_true",
                        help="Show token usage and response time after each exchange")
    parser.add_argument("--cbt", action="store_true",
                        help="Start with CBT journaling session")
    parser.add_argument("--narrative", action="store_true",
                        help="Start narrative therapy directly")
    parser.add_argument("--finalize", action="store_true",
                        help="Start finalize directly (reads from archived/summarize.txt)")
    parser.add_argument("--origin_story", type=str, default="story/example.txt",
                        help="Path to story file (default: story/example.txt)")
    args = parser.parse_args()

    # Check that at least one mode is specified
    if not args.cbt and not args.narrative and not args.finalize:
        print("Please specify --cbt, --narrative, or --finalize")
        return

    agent = JournalAgent(model=args.model)
    print(f"Using model: {MODELS[args.model]}")

    if args.finalize:
        # Start finalize directly with summary from archived/summarize.txt
        with open("archived/summarize.txt", "r") as f:
            summary = f.read().strip()
        agent.final_summary = summary
        agent.origin_reframed_journal = summary  # For feedback prompt
        print(f"Loaded summary from: archived/summarize.txt")
        print("\n--- Finalizing Journal ---\n")

        # Get title
        title = input("Enter journal title: ").strip()
        if title.lower() in ("quit", "exit", "q"):
            print("\nGoodbye!")
            return

        response = agent.finalize(title)
        print(f"\n{response}")
        print_metadata(agent, args.show_metadata)

        # Finalize loop for emotion questions
        while True:
            try:
                user_input = get_input()
                if user_input is None or user_input.lower() == "end":
                    print(f"\nJournal '{agent.journal_title}' archived!")
                    break
                if not user_input:
                    continue
                agent.finalize_receive(user_input)
                response = agent.finalize_reply()
                print(f"\n{response}")
                print_metadata(agent, args.show_metadata)
            except KeyboardInterrupt:
                break
        print("\nGoodbye!")
        return

    if args.narrative:
        # Start narrative therapy directly with story from file
        with open(args.origin_story, "r") as f:
            reframed_journal = f.read().strip()
        print(f"Loaded story from: {args.origin_story}")
        print("\n--- Narrative Therapy Session ---\n")
        response = agent.start_narrative(reframed_journal=reframed_journal)
        print(f"\n{response}")
        print_metadata(agent, args.show_metadata)

        run_narrative(agent, args.show_metadata)
    else:
        # Start with CBT journaling
        run_cbt(agent, args.show_metadata)

    print("\nGoodbye!")


if __name__ == "__main__":
    main()
