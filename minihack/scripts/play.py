#!/usr/bin/env python
#
# Copyright (c) Facebook, Inc. and its affiliates.
import argparse
import ast
import contextlib
import random
import os
import termios
import time
import timeit
import tty

import gymnasium as gym

import nle  # noqa: F401
import minihack  # noqa: F401
from nle import nethack
import tempfile
import shutil
import glob


_ACTIONS = tuple(
    [nethack.MiscAction.MORE]
    + list(nethack.CompassDirection)
    + list(nethack.CompassDirectionLonger)
)


@contextlib.contextmanager
def dummy_context():
    yield None


@contextlib.contextmanager
def no_echo():
    tt = termios.tcgetattr(0)
    try:
        tty.setraw(0)
        yield
    finally:
        termios.tcsetattr(0, termios.TCSAFLUSH, tt)


def get_action(env, action_mode, is_raw_env):
    if action_mode == "random":
        if not is_raw_env:
            action = env.action_space.sample()
        else:
            action = random.choice(_ACTIONS)
    elif action_mode == "human":
        while True:
            with no_echo():
                ch = ord(os.read(0, 1))
            if ch == nethack.C("c"):
                print("Received exit code {}. Aborting.".format(ch))
                return None
            try:
                if is_raw_env:
                    action = ch
                else:
                    action = env.unwrapped.actions.index(ch)
                break
            except ValueError:
                print(
                    (
                        "Selected action '%s' is not in action list. "
                        "Please try again."
                    )
                    % chr(ch)
                )
                continue
    return action


def play(
    env,
    mode,
    ngames,
    max_steps,
    seeds,
    savedir,
    no_render,
    render_mode,
    debug,
    save_gif,
    gif_path,
    gif_duration,
):
    env_name = env
    is_raw_env = env_name == "raw"

    if is_raw_env:
        if savedir is not None:
            os.makedirs(savedir, exist_ok=True)
            ttyrec = os.path.join(savedir, "nle.ttyrec.bz2")
        else:
            ttyrec = "/dev/null"
        env = nethack.Nethack(ttyrec=ttyrec)
    else:
        env_kwargs = dict(
            savedir=savedir,
            max_episode_steps=max_steps,
        )
        if save_gif:
            env_kwargs["observation_keys"] = ("pixel_crop",)
            try:
                import PIL.Image
            except ModuleNotFoundError:
                raise ModuleNotFoundError(
                    "To safe GIF files of trajectories, please install Pillow:"
                    " pip install Pillow"
                )

        env = gym.make(
            env_name,
            render_mode=render_mode,
            **env_kwargs,
        )
        if seeds is not None:
            env.unwrapped.seed(seeds)
        if not no_render:
            print("Available actions:", env.unwrapped.actions)

    obs, info = env.reset()

    steps = 0
    episodes = 0
    reward = 0.0
    action = None

    mean_sps = 0
    mean_reward = 0.0

    total_start_time = timeit.default_timer()
    start_time = total_start_time

    if save_gif:
        # Create a tmp directory for individual screenshots
        tmpdir = tempfile.mkdtemp()

    while True:
        if not no_render:
            if not is_raw_env:
                print("Previous reward:", reward)
                if action is not None:
                    print("Previous action: %s" % repr(env.unwrapped.actions[action]))
                env.render()
            else:
                print("Previous action:", action)
                _, chars, _, _, blstats, message, *_ = obs
                msg = bytes(message)
                print(msg[: msg.index(b"\0")])
                for line in chars:
                    print(line.tobytes().decode("utf-8"))
                print(blstats)

        if save_gif:
            obs_image = PIL.Image.fromarray(obs["pixel_crop"])
            obs_image.save(os.path.join(tmpdir, f"e_{episodes}_s_{steps}.png"))

        action = get_action(env, mode, is_raw_env)
        if action is None:
            break

        if is_raw_env:
            obs, done = env.step(action)
        else:
            # Truncated flag added for Gymnasium upgrade. To
            # maintain backward compatibility, it's not used
            # for now.
            obs, reward, done, truncated, info = env.step(action)
        steps += 1

        if is_raw_env:
            done = done or steps >= max_steps  # NLE does this by default.
        else:
            mean_reward += (reward - mean_reward) / steps

        if not done:
            continue

        time_delta = timeit.default_timer() - start_time

        if not is_raw_env:
            print("Final reward:", reward)
            print("End status:", info["end_status"].name)
            print("Mean reward:", mean_reward)

        sps = steps / time_delta
        print("Episode: %i. Steps: %i. SPS: %f" % (episodes, steps, sps))

        episodes += 1
        mean_sps += (sps - mean_sps) / episodes

        start_time = timeit.default_timer()

        steps = 0
        mean_reward = 0.0

        if episodes == ngames:
            break
        env.reset()

    if save_gif:
        # Make the GIF and delete the temporary directory
        png_files = glob.glob(os.path.join(tmpdir, "e_*_s_*.png"))
        png_files.sort(key=os.path.getmtime)

        img, *imgs = [PIL.Image.open(f) for f in png_files]
        img.save(
            fp=gif_path,
            format="GIF",
            append_images=imgs,
            save_all=True,
            duration=gif_duration,
            loop=0,
        )
        shutil.rmtree(tmpdir)

        print("Saving replay GIF at {}".format(os.path.abspath(gif_path)))
    env.close()
    print(
        "Finished after %i episodes and %f seconds. Mean sps: %f"
        % (episodes, timeit.default_timer() - total_start_time, mean_sps)
    )


def main():
    parser = argparse.ArgumentParser(description="Play tool.")
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enables debug mode, which will drop stack into "
        "an ipdb shell if an exception is raised.",
    )
    parser.add_argument(
        "-m",
        "--mode",
        type=str,
        default="human",
        choices=["human", "random"],
        help="Control mode. Defaults to 'human'.",
    )
    parser.add_argument(
        "-e",
        "--env",
        type=str,
        default="MiniHack-Room-Random-5x5-v0",
        help="Gymnasium environment spec. Defaults to 'MiniHack-Room-Random-5x5-v0'.",
    )
    parser.add_argument(
        "-n",
        "--ngames",
        type=int,
        default=1,
        help="Number of games to be played before exiting. "
        "NetHack will auto-restart if > 1.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=10000,
        help="Number of maximum steps per episode.",
    )
    parser.add_argument(
        "--seeds",
        default=None,
        help="Seeds to send to NetHack. Can be a dict or int. "
        "Defaults to None (no seeding).",
    )
    parser.add_argument(
        "--savedir",
        default="nle_data/play_data",
        help="Directory path where data will be saved. "
        "Defaults to 'nle_data/play_data'.",
    )
    parser.add_argument(
        "--no-render", action="store_true", help="Disables env.render()."
    )
    parser.add_argument(
        "--render_mode",
        type=str,
        default="human",
        choices=["human", "full", "ansi"],
        help="Render mode. Defaults to 'human'.",
    )
    parser.add_argument(
        "--save_gif",
        dest="save_gif",
        action="store_true",
        help="Saving a GIF replay of the evaluated episodes.",
    )
    parser.add_argument(
        "--no-save_gif",
        dest="save_gif",
        action="store_false",
        help="Do not save GIF.",
    )
    parser.set_defaults(save_gif=False)
    parser.add_argument(
        "--gif_path",
        type=str,
        default="replay.gif",
        help="Where to save the produced GIF file.",
    )
    parser.add_argument(
        "--gif_duration",
        type=int,
        default=300,
        help="The duration of each gif image.",
    )
    flags = parser.parse_args()

    if flags.debug:
        import ipdb

        cm = ipdb.launch_ipdb_on_exception
    else:
        cm = dummy_context

    with cm():
        if flags.seeds is not None:
            # to handle both int and dicts
            flags.seeds = ast.literal_eval(flags.seeds)

        if flags.savedir == "args":
            flags.savedir = "{}_{}_{}.zip".format(
                time.strftime("%Y%m%d-%H%M%S"), flags.mode, flags.env
            )

        play(**vars(flags))


if __name__ == "__main__":
    main()
