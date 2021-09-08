#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2021 The WfCommons Team.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import uuid

from logging import Logger
from typing import Optional

from .abstract_translator import Translator
from ...common.file import FileLink


class PegasusTranslator(Translator):
    """A WfFormat parser for creating Pegasus workflow applications.

    :param workflow_json_file:
    :type workflow_json_file: str
    :param logger: The logger where to log information/warning or errors (optional).
    :type logger: Logger
    """

    def __init__(self,
                 workflow_json_file: str,
                 logger: Optional[Logger] = None) -> None:
        """Create an object of the translator."""
        super().__init__(workflow_json_file, logger)

        self.script = "import os\n" \
                      "from Pegasus.api import *\n\n\n" \
                      "def which(file):\n" \
                      "    for path in os.environ['PATH'].split(os.pathsep):\n" \
                      "        if os.path.exists(os.path.join(path, file)):\n" \
                      "            return os.path.join(path, file)\n" \
                      "    return None\n\n\n"
        self.parsed_tasks = []
        self.tasks_map = {}
        self.task_counter = 1

    def translate(self, output_file: str) -> None:
        """
        Translates a workflow description (WfFormat) into a Pegasus workflow application.

        :param output_file: The name of the output file (e.g., workflow.py).
        :type output_file: str
        """
        # overall workflow
        self.script += f"wf = Workflow('{self.instance.name}', infer_dependencies=True)\n" \
                       "tc = TransformationCatalog()\n" \
                       "rc = ReplicaCatalog()\n\n"
        self.script += "task_output_files = {}\n\n"

        # transformation catalog
        transformations = []
        for task in self.tasks.values():
            if task.category not in transformations:
                transformations.append(task.category)
                self.script += f"transformation_path = which('{task.program}')\n" \
                               "if transformation_path is None:\n" \
                               f"    raise RuntimeError('Unable to find {task.program}')\n" \
                               f"transformation = Transformation('{task.category}', site='local',\n" \
                               f"                                pfn='{task.program}',\n" \
                               "                                is_stageable=True)\n" \
                               "transformation.add_env(PATH='/usr/bin:/bin:.')\n" \
                               "transformation.add_profiles(Namespace.CONDOR, 'request_disk', '10')\n" \
                               "tc.add_transformations(transformation)\n\n"

        # adding tasks
        for task_name in self.parent_task_names:
            self._add_task(task_name)
            # input file
            task = self.tasks[task_name]
            for file in task.files:
                if file.link == FileLink.INPUT:
                    self.script += f"in_file_{self.task_counter} = File('{file.name}')\n"
                    self.script += f"rc.add_replica('local', '{file.name}', 'file://' + os.getcwd() + " \
                                   f"'/data/{file.name}')\n"
                    self.script += f"{self.tasks_map[task_name]}.add_inputs(in_file_{self.task_counter})\n" \
                                   f"print('{file.name}')\n"

        self.script += "\n"

        # write out the workflow
        self.script += "wf.add_replica_catalog(rc)\n" \
                       "wf.add_transformation_catalog(tc)\n" \
                       f"wf.write('{self.instance.name}-benchmark-workflow.yml')\n"

        # write script to file
        with open(output_file, 'w') as out:
            out.write(self.script)

    def _add_task(self, task_name: str, parent_task: Optional[str] = None) -> None:
        """
        Add a task and its dependencies to the workflow.

        :param task_name: name of the task
        :type task_name: str
        :param parent_task: name of the parent task
        :type parent_task: Optional[str]
        """
        if task_name not in self.parsed_tasks:
            task = self.tasks[task_name]
            job_name = f"job_{self.task_counter}"
            self.script += f"{job_name} = Job('{task.category}', _id='{task_name}')\n"
            task.args.insert(0, task_name.split("_")[0])

            # output file
            for file in task.files:
                if file.link == FileLink.OUTPUT:
                    out_file = file.name
                    task.args.append(f"--out={out_file}")
                    self.script += f"out_file_{self.task_counter} = File('{out_file}')\n"
                    self.script += f"task_output_files['{job_name}'] = out_file_{self.task_counter}\n"
                    self.script += f"{job_name}.add_outputs(out_file_{self.task_counter}, " \
                                   "stage_out=True, register_replica=True)\n"

            # arguments
            args = ", ".join(f"'{a}'" for a in task.args)
            self.script += f"{job_name}.add_args({args})\n"

            self.script += f"wf.add_jobs({job_name})\n\n"
            self.task_counter += 1
            self.parsed_tasks.append(task_name)
            self.tasks_map[task_name] = job_name

            for node in self.instance.instance['workflow']['jobs']:
                if node['name'] == task_name:
                    for child_task_name in node['children']:
                        self._add_task(child_task_name, job_name)

        if parent_task:
            self.script += f"{self.tasks_map[task_name]}.add_inputs(task_output_files['{parent_task}'])\n"
            self.script += f"wf.add_dependency({self.tasks_map[task_name]}, parents=[{parent_task}])\n\n"
