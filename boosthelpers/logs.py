#/usr/bin/env python
# -*- coding: utf-8 -*-

from os import path
from enum import Enum, unique
import re
import sys
from conans.client.output import ConanOutput

class ILogsParser(object):

    _logfile = None

    def __init__(self, logfile):
        if not path.exists(logfile):
            raise IOError("file {} not found".format(logfile))
        self._logfile = logfile

    def _read(self):
        raise Exception("NotImplementedException")

    def parse(self):
        with open(self._logfile) as logs:
            self._read(logs)

    @property
    def summary(self):
        raise Exception("NotImplementedException")

    def __str__(self):
        return str(self.summary)


class BjamLogsParser(ILogsParser):

    _passed = list()
    _failed = list()
    _unknown = list()

    _lastline = ""
    _build_passed = False
    _counter = 1

    class Recorder(object):

        _recording = False
        _cache = ""

        def clear(self):
            self._cache = ""

        def start(self):
            if not self._recording:
                self.clear()
            self._recording = True

        def stop(self):
            self._recording = False

        def feed(self, context):
            if self._recording:
                self._cache += context
                #print(context)

        @property
        def record(self):
            return self._cache

        @property
        def is_recording(self):
            return self._recording

    _recorder = Recorder()

    def _register(self, registry, line, context=""):
        registry.append((self._counter, line, context))
        self._counter += 1

    def _parse_line(self, line):

        @unique
        class BuildTypes(Enum):
            FAILURE = 1
            FAILURE_UNITTEST = 2
            SUCCESS = 3
            SUCCESS_UNITTEST = 4
            SUCCESS_LIB = 5

        self._lastline = line
        status = None
        if line.startswith("...failed") \
            and re.match(r'^\.\.\.failed updating [0-9]+ targets?\.\.\.$', line) is None:
            status = BuildTypes.FAILURE_UNITTEST
        elif line.startswith("failed to write"):
            status = BuildTypes.FAILURE
        elif line.startswith("**passed**"):
            status = BuildTypes.SUCCESS_UNITTEST
        elif line.startswith("common.copy"):
            status = BuildTypes.SUCCESS_LIB
        elif "The Boost C++ Libraries were successfully built!" in line:
            status = BuildTypes.SUCCESS
        elif re.match(r'\s*"?((g|clang)\+\+|cl|msvc|compile\-c\-c\+\+).*$', line) is not None \
             or line.startswith("====== BEGIN OUTPUT ======") \
             or line.startswith("error:"):
            if not line.startswith("cl"):
                self._recorder.stop()
            self._recorder.start()
            self._recorder.feed(line)
        elif line.startswith("====== END OUTPUT ======"):
            self._recorder.feed(line)
            self._recorder.stop()
        else:
            self._recorder.feed(line)

        if status is not None:
            self._recorder.stop()
            group = None
            if status == BuildTypes.SUCCESS:
                self._recorder.clear()
                self._build_passed = True
            elif status == BuildTypes.SUCCESS_LIB:
                self._recorder.clear()
                group = self._passed
                name = re.search(r'lib[a-zA-Z0-9_\-]+\.(a|so|lib|dll)$', line)
                if name is not None:
                    line = name.group(0)

            elif status == BuildTypes.SUCCESS_UNITTEST:
                self._recorder.clear()
                group = self._passed
                name = re.search(r'([a-zA-Z0-9_]+)\.(test)$', line)
                if name is not None:
                    line = name.group(1)

            elif status == BuildTypes.FAILURE_UNITTEST:
                group = self._failed
                name = re.search(r'([a-zA-Z0-9_]+(\.(o(bj)?|run|exe|pdb))?)\.\.\.$', line)
                if name is not None:
                    if name.group(1).endswith(".pdb"):
                        line = name.group(1).replace("pdb", "exe")
                    else:
                        line = name.group(1)
            elif status == BuildTypes.FAILURE:
                group = self._failed

            if group is not None:
                self._register(group, line, self._recorder.record)


    def _read(self, logs):
        for line in logs:
            if len(line.rstrip()) > 0:
                self._parse_line(line)

        if not self._build_passed:
            if self._lastline.startswith("...found"):
                self._register(self._unknown, "WTF ? oO")
            elif not self._lastline.startswith("...updated"):
                line = "Malformed file: truncated ? not a bjam log file ?"
                if self._lastline.startswith("error:"):
                    line = self._recorder.record
                self._register(self._failed, line)

    @property
    def passed(self):
        return len(self._passed)

    @property
    def failed(self):
        return len(self._failed)

    @property
    def unknown(self):
        return len(self._unknown)

    @property
    def summary(self):
        return {
                'passed': (self.passed, self._passed),
                'failed': (self.failed, self._failed),
                'unknown': (self.unknown, self._unknown)
                }

class BJamLogsReportFormatter(object):

    _summary = None
    _output = ConanOutput(sys.stdout, True)

    def error(self, msg):
        self._output.error(msg)

    def warn(self, msg):
        self._output.warn(msg)

    def info(self, msg):
        self._output.info(msg)

    def format(self, summary):
        print("Summary :")
        print("---------")
        print("  {} failed".format(summary['failed'][0]))
        print("  {} unknown".format(summary['unknown'][0]))
        print("  {} passed\n".format(summary['passed'][0]))

        history = [(number, category, module, details) for category, (_, msgs) in summary.items() for (number, module, details) in msgs]
        history = sorted(history, key=lambda x: x[0])

        for (number, category, module, details) in history:
            if category == "failed":
                self.error("{}: {}".format(number, module))
                print(details)
            elif category == "passed":
                self.info("{}: {}{}".format(number, module, details))
            elif category == "unknown":
                self.warn("{}: {}{}".format(number, module, details))

if __name__ == '__main__':
    def parse_args():
        import argparse
        def check_path(p):
            """
                Paths checker
            """
            if not path.exists(p):
                raise ValueError("{path} does not exist".format(path=p))
            return p

        parser = argparse.ArgumentParser(description="Parse bjam's logs.")
        parser.add_argument('-f', '--file',
                            metavar='FILE',
                            required=True,
                            type=check_path,
                            help="bjam's logs")
        args = parser.parse_args()
        return args

    args = parse_args()
    parser = BjamLogsParser(args.file)
    parser.parse()
    formatter = BJamLogsReportFormatter()
    formatter.format(parser.summary)
