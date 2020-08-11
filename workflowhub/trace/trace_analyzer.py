#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2020 The WorkflowHub Team.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

import logging

from logging import Logger
from os import path
from typing import Any, Dict, List, Optional, Tuple

from .trace import Trace
from ..common.job import Job
from ..common.file import FileLink
from ..utils import best_fit_distribution


class TraceAnalyzer:
    """Set of tools for analyzing collections of traces.

    :param logger: The logger where to log information/warning or errors.
    :type logger: Logger
    """

    def __init__(self, logger: Logger = None) -> None:
        """Create an object of the trace analyzer."""
        self.logger: Logger = logging.getLogger(__name__) if logger is None else logger
        self.traces: List[Trace] = []
        self.jobs_summary: Dict[str, List:Job] = {}
        self.traces_summary: Dict[str, Dict[str, Any]] = {}

    def append_trace(self, trace: Trace) -> None:
        """Append a workflow trace object to the trace analyzer.

        .. code-block:: python

            trace = Trace(input_trace = 'trace.json', schema = 'schema.json')
            trace_analyzer = TraceAnalyzer()
            trace_analyzer.append_trace(trace)

        :param trace: A workflow trace object.
        :type trace: Trace
        """
        if trace not in self.traces:
            self.traces.append(trace)
            self.logger.debug('Appended trace: {} ({} jobs)'.format(trace.name, len(trace.workflow.nodes)))

    def build_summary(self, jobs_list: List[str], include_raw_data: Optional[bool] = True) -> Dict[str, Dict[str, Any]]:
        """Analyzes appended traces and produce a summary of the analysis per job prefix.

        .. code-block:: python

            workflow_jobs = ['sG1IterDecon', 'wrapper_siftSTFByMisfit']
            traces_summary = trace_analyzer.build_summary(workflow_jobs, include_raw_data=False)

        :param jobs_list: List of workflow jobs prefix (e.g., mProject, sol2sanger, add_replace)
        :type jobs_list: List[str]
        :param include_raw_data: Whether to include the raw data in the trace summary.
        :type include_raw_data: bool

        :return: A summary of the analysis of traces in the form of a dictionary in which keys are job prefixes.
        :rtype: Dict[str, Dict[str, Any]]
        """
        self.logger.debug('Building summary for {} traces'.format(len(self.traces)))

        # build jobs summary
        for trace in self.traces:
            self.logger.debug('Parsing trace: {} ({} jobs)'.format(trace.name, len(trace.workflow.nodes)))
            for node in trace.workflow.nodes.data():
                job: Job = node[1]['job']
                job_name: str = [j for j in jobs_list if j in job.name][0]

                if job_name not in self.jobs_summary:
                    self.jobs_summary[job_name] = []
                self.jobs_summary[job_name].append(job)

        # build traces summary
        for job_name in self.jobs_summary:
            runtime_list: List[float] = []
            inputs_dict: Dict[str, Any] = {}
            outputs_dict: Dict[str, Any] = {}

            for job in self.jobs_summary[job_name]:
                runtime_list.append(job.runtime)

                for file in job.files:
                    extension: str = path.splitext(file.name)[1] if '.' in file.name else file.name
                    if file.link == FileLink.INPUT:
                        _append_file_to_dict(extension, inputs_dict, file.size)
                    elif file.link == FileLink.OUTPUT:
                        _append_file_to_dict(extension, outputs_dict, file.size)

            _best_fit_distribution_for_file(inputs_dict, include_raw_data)
            _best_fit_distribution_for_file(outputs_dict, include_raw_data)

            self.traces_summary[job_name] = {
                'runtime': {
                    'min': min(runtime_list),
                    'max': max(runtime_list),
                    'distribution': _json_format_distribution_fit(best_fit_distribution(runtime_list))
                },
                'input': inputs_dict,
                'output': outputs_dict
            }
            if include_raw_data:
                self.traces_summary[job_name]['runtime']['data'] = runtime_list

        return self.traces_summary


def _append_file_to_dict(extension: str, dict_obj: Dict[str, Any], file_size: int) -> None:
    """Add a file size to a file type extension dictionary.

    :param extension: File type extension.
    :type extension: str
    :param dict_obj: Dictionary of file type extensions.
    :type dict_obj: Dict[str, Any]
    :param file_size: File size in bytes.
    :type file_size: int
    """
    if extension not in dict_obj:
        dict_obj[extension] = {'data': [], 'distribution': None}
    dict_obj[extension]['data'].append(file_size)


def _best_fit_distribution_for_file(dict_obj, include_raw_data) -> None:
    """Find the best fit distribution for a file.

    :param dict_obj: Dictionary of file type extensions.
    :type dict_obj: Dict[str, Any]
    :param include_raw_data:
    :type include_raw_data: bool
    """
    for ext in dict_obj:
        dict_obj[ext]['min'] = min(dict_obj[ext]['data'])
        dict_obj[ext]['max'] = max(dict_obj[ext]['data'])
        if dict_obj[ext]['min'] != dict_obj[ext]['max']:
            dict_obj[ext]['distribution'] = _json_format_distribution_fit(
                best_fit_distribution(dict_obj[ext]['data']))
        if not include_raw_data:
            del dict_obj[ext]['data']


def _json_format_distribution_fit(dist_tuple: Tuple) -> Dict[str, Any]:
    """Format the best fit distribution data into a dictionary

    :param dist_tuple: Tuple containing best fit distribution name and parameters.
    :type dist_tuple: Tuple

    :return:
    :rtype: Dict[str, Any]
    """
    formatted_entry = {'name': dist_tuple[0], 'params': []}
    for p in dist_tuple[1]:
        formatted_entry['params'].append(p)
    return formatted_entry
