#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2021 The WfCommons Team.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import glob
import json
import logging
import os
import pathlib
import subprocess
import uuid

from logging import Logger
from typing import Dict, Optional, List, Type

from numpy import copyto

from ..wfchef.wfchef_abstract_recipe import WfChefWorkflowRecipe
from ..wfgen import WorkflowGenerator

this_dir = pathlib.Path(__file__).resolve().parent


class WorkflowBenchmark:
    """Generate a workflow benchmark instance based on a workflow recipe (WfChefWorkflowRecipe)

    :param recipe: A workflow recipe.
    :type recipe: Type[WfChefWorkflowRecipe]
    :param num_tasks: Total number of tasks in the benchmark workflow.
    :type num_tasks: int
    :param logger: The logger where to log information/warning or errors.
    :type logger: Optional[Logger]
    """

    def __init__(self, recipe: Type[WfChefWorkflowRecipe], num_tasks: int, logger: Optional[Logger] = None) -> None:
        """Create an object that represents a workflow benchmark generator."""
        self.logger: Logger = logging.getLogger(__name__) if logger is None else logger
        self.recipe = recipe
        self.num_tasks = num_tasks

    def create_benchmark(self,
               save_dir: pathlib.Path,
               percent_cpu: float = 0.6,
               cpu_work: Optional[int] = 100,
               data_footprint: Optional[int] = None,
               lock_files_folder: Optional[pathlib.Path] = None,
               create: Optional[bool] = True,
               path: Optional[pathlib.Path] = None) -> pathlib.Path:
        """Create a workflow benchmark.

        :param save_dir: Folder to generate the workflow benchmark JSON instance and input data files.
        :type save_dir: pathlib.Path
        :param percent_cpu:
        :type percent_cpu: float
        :param cpu_work:
        :type cpu_work: int
        :param data_footprint: Size of input/output data files per workflow task (in MB).
        :type data_footprint: Optional[int]
        :param lock_files_folder:
        :type lock_files_folder: Optional[pathlib.Path]
        :param create:
        :type create: Optional[bool]
        :param path:
        :type path: Optional[pathlib.Path]

        :return: The path to the workflow benchmark JSON instance.
        :rtype: pathlib.Path
        """
        save_dir = save_dir.resolve()
        save_dir.mkdir(exist_ok=True, parents=True)

        if create:
            self.logger.debug("Generating workflow")
            generator = WorkflowGenerator(self.recipe.from_num_tasks(self.num_tasks))
            workflow = generator.build_workflow()
            name = f"{workflow.name.split('-')[0]}-Benchmark"
            workflow_savepath = save_dir.joinpath(f"{name}-{self.num_tasks}").with_suffix(".json")
            workflow.write_json(str(workflow_savepath))
            wf = json.loads(workflow_savepath.read_text())
        else:
            # TODO: should we keep this, or is it only for testing?
            wf = json.loads(path.read_text())

        # Creating the lock files
        create_lock_files = True
        if lock_files_folder:
            if lock_files_folder.exists():
                self.logger.debug(f"Creating lock files at: {lock_files_folder.resolve()}")
            else:
                self.logger.warning(f"Could not find folder to create lock files: {lock_files_folder.resolve()}\n"
                                    f"You will need to create them manually: 'cores.txt.lock' and 'cores.txt'")
                create_lock_files = False
        else:
            self.logger.warning("No lock files folder provided. Benchmark workflow will be generated using '/tmp' "
                                "as the folder for creating lock files.")
            lock_files_folder = pathlib.Path("/tmp")

        lock = lock_files_folder.joinpath("cores.txt.lock")
        cores = lock_files_folder.joinpath("cores.txt")
        if create_lock_files:
            with lock.open("w+"), cores.open("w+"):
                pass

        # Setting the parameters for the arguments section of the JSON
        params = [f"--path-lock={lock}",
                  f"--path-cores={cores}",
                  f"--percent-cpu={percent_cpu}",
                  f"--cpu-work={cpu_work}"]

        wf["name"] = name
        for job in wf["workflow"]["jobs"]:
            job["files"] = []
            job.setdefault("command", {})
            job["command"]["program"] = f"{this_dir.joinpath('wfperf_benchmark.py')}"
            job["command"]["arguments"] = [job["name"]]
            job["command"]["arguments"].extend(params)
            if "runtime" in job:
                del job["runtime"]

        num_sys_files, num_total_files = input_files(wf)

        # whether to generate IO
        if data_footprint:
            self.logger.debug(f"Number of input files to be created by the system: {num_sys_files}")
            self.logger.debug(f"Total number of files used by the workflow: {num_total_files}")
            file_size = round(data_footprint / num_total_files)
            self.logger.debug(f"Every input/output file is of size: {file_size}")

            for job in wf["workflow"]["jobs"]:
                job["command"]["arguments"].extend([
                    "--data",
                    f"--file-size={file_size}"
                ])

            add_io_to_json(wf, file_size)

            self.logger.debug("Generating system files.")
            generate_sys_data(num_sys_files, file_size, save_dir)

        json_path = save_dir.joinpath(f"{name}-{self.num_tasks}").with_suffix(".json")
        self.logger.info(f"Saving benchmark workflow: {json_path}")
        json_path.write_text(json.dumps(wf, indent=4))

        return json_path


    def run(self, json_path: pathlib.Path, save_dir: pathlib.Path):
        """Run the benchmark workflow locally (for test purposes only).
        """
        self.logger.debug("Running")
        try:
            wf = json.loads(json_path.read_text())
            with save_dir.joinpath(f"run.txt").open("w+") as fp:
                procs: List[subprocess.Popen] = []
                for job in wf["workflow"]["jobs"]:
                    executable = job["command"]["program"]
                    arguments = job["command"]["arguments"]
                    if "--data" in arguments:
                        files = assigning_correct_files(job)
                        program = ["time","python", executable, *arguments, *files]
                    else:
                        program = ["time","python", executable, *arguments]
                    folder = pathlib.Path(this_dir.joinpath(f"wfperf_execution/{uuid.uuid4()}"))
                    folder.mkdir(exist_ok=True, parents=True)
                    os.chdir(str(folder))
                    procs.append(subprocess.Popen(program, stdout=fp, stderr=fp))
                    os.chdir("../..")
                for proc in procs:
                    proc.wait()  
            cleanup_sys_files()
        except Exception as e:
            subprocess.Popen(["killall", "stress"])
            cleanup_sys_files()
            import traceback
            traceback.print_exc()
            raise FileNotFoundError("Not able to find the executable.")
        
def generate_sys_data(num_files: int, file_total_size: int, save_dir: pathlib.Path):
    """Generate workflow's input data

    :param num_files:
    :type num_files: int
    :param file_total_size:
    :type file_total_size: int
    :param save_dir: Folder to generate the workflow benchmark's input data files.
    :type save_dir: pathlib.Path
    """
    file_total_size = num_files * file_total_size
    for i in range(num_files):
        file = f"{save_dir.joinpath(f'sys_input_{i}.txt')}"
        with open(file, 'wb') as fp:
            fp.write(os.urandom(file_total_size)) 
        print(f"Created file: {file}")

def assigning_correct_files(job: Dict[str, str]) -> List[str]:
    files = []
    for file in job["files"]:
        if file["link"] == "input":
            files.append(file["name"])
    return files


def cleanup_sys_files():
    """Remove files already used
    """
    input_files = glob.glob("*input*.txt")
    output_files = glob.glob("*output.txt")
    all_files = input_files + output_files
    for t in all_files:
        os.remove(t)

def add_io_to_json(wf: Dict[str, Dict], file_size: int) -> None:
    """Add input and output files to JSON
    """
    i = 0
    all_jobs = {
        job["name"]: job
        for job in wf["workflow"]["jobs"]
    }

    for job in wf["workflow"]["jobs"]:
        job.setdefault("files", [])
        job["files"].append(
            {
                "link": "output",
                "name": f"{job['name']}_output.txt",
                "size": file_size
            }
        )

        parents = [parent for parent in job["parents"]]
        if not parents:
            job["files"].append(
                {
                    "link": "input",
                    "name": f"sys_input_{i}.txt",
                    "size": file_size
                }
            )
            i += 1
        else:
            for parent in parents:
                job["files"].extend(
                    [
                        {
                            "link": "input",
                            "name": item["name"],
                            "size": item["size"]
                        }
                        for item in all_jobs[parent]["files"] if item["link"] == "output"
                    ]
                )


def input_files(wf: Dict[str, Dict]):
    """Calculate total number of files needed
    """
    tasks_need_input = 0
    tasks_dont_need_input = 0

    for job in wf["workflow"]["jobs"]:
        parents = [parent for parent in job["parents"]]
        if not parents:
            tasks_need_input += 1
        else:
            tasks_dont_need_input += 1

    total_num_files = tasks_need_input * 2 + tasks_dont_need_input

    return tasks_need_input, total_num_files
