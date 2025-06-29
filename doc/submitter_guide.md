---
title: "Submitter guide"
date: 2025-05-13
draft: false
weight: 20
description: "How to submit build and test reports with KCIDB"
---
Here's what you need to do to submit your reports.

1. Get submission credentials and parameters.
2. Install KCIDB.
3. Generate some report data.
4. Submit report data.
5. Go to 3, if you have more.

You don't need to run a daemon, just execute command-line tools (or use the
Python 3 library, if you're feeling fancy).

1\. Get submission credentials and parameters
---------------------------------------------

Write to [kernelci@lists.linux.dev](mailto:kernelci@lists.linux.dev),
introduce yourself, and explain what you want to submit (better, show
preliminary report data). Once your request is approved, you will get a token,
which you can use to authenticate yourself with KCIDB tools/library.

Token and REST endpoint can be set in the environment variable:
```bash
export KCIDB_REST="https://token@db.kernelci.org/"
```

We will also need to agree on the "origin" string identifying your system
among other submitters. We'll use `submitter` in examples below.

Initially it is recommended to use the "playground" token and endpoint, which
will be provided to new users. This is a special setup for testing and
experimenting with the system.

Once you feel comfortable and ready, we'll switch you to the "production"
token and endpoint, which will be used for production data.

2\. Install KCIDB
-----------------


KCIDB employs continuous integration and delivery, and aims to keep
the code working at all times.

Please install the latest version from GitHub:


```bash
pip3 install --user 'git+https://git@github.com/kernelci/kcidb.git'
```

Then make sure your PATH includes the `~/.local/bin` directory, e.g. with:

    export PATH="$PATH":~/.local/bin

See [Installation](../installation) for alternatives, and if you know your
Python, feel free to do it your way!

To test your installation, authentication, and the parameters you received,
submit an empty report:

```console
$ echo '{"version":{"major":4,"minor":3}}' |
        kcidb-submit -p kernelci-production -t playground_kcidb_new
```

The command should execute without errors, produce the submitted message ID on
output, and finish with zero exit status.

3\. Generate some report data
-----------------------------

`kcidb-schema` tool will output the current schema version.

However, all tools will accept data complying with older schema versions. Pipe
your data into `kcidb-validate` tool to check if it will be accepted.

Here's a minimal report, containing no data:

```json
{
    "version": {
        "major": 4,
        "minor": 3
    }
}
```

You can submit such a report, it will be accepted, but will have no effect on
the database or notifications.

### Objects

The schema describes five types of objects which can be submitted
independently or in any combination:
* "checkout" - a checkout of the code being built and tested
* "build" - a build of a specific checkout
* "test" - an execution of a test on a specific build in specific environment
* "issue" - an issue found either in the kernel code, a test, or a CI system
* "incident" - a record of an issue appearing in a build or a test run

Each of these object types refers to on or two of the others IDs. The only
required fields for each object are their own IDs, IDs of the parent objects
(except for checkouts and issues), and the origin. Objects of each type are
stored in their own top-level array named respectively (in plural).

Here's an example of a report, containing only the required fields for a
checkout with one build and one test, as well as one issue and one incident:

```json
{
    "checkouts": [
        {
            "id": "submitter:32254",
            "origin": "submitter"
        }
    ],
    "builds": [
        {
            "id": "submitter:32254",
            "checkout_id": "submitter:c9c9735c46f589b9877b7fc00c89ef1b61a31e18",
            "origin": "submitter"
        }
    ],
    "tests": [
        {
            "id": "submitter:114353810",
            "build_id": "submitter:956769",
            "origin": "submitter"
        }
    ],
    "issue": [
        {
            "id": "submitter:124853810",
            "version": 1,
            "origin": "submitter"
        }
    ],
    "incident": [
        {
            "id": "submitter:1084645810",
            "issue_id": "submitter:956769",
            "origin": "submitter",
            "issue_version": 0
        }
    ],
    "version": {
        "major": 4,
        "minor": 3
    }
}
```

#### Object IDs

All object IDs have to start with your "origin" string, followed by the colon
`:` character, followed by your origin-local ID. The origin-local ID can be
any string, but must identify the object uniquely among all objects of the
same type you submit. E.g.:

    submitter:12
    submitter:db58a18be346
    submitter:test-394
    submitter:build-394

### Properties

Once you get the required properties (IDs and origins) generated, and have
your objects accepted by KCIDB, you can start adding the optional fields.
Some good starting candidates are described below. See the schema for more.

#### Checkouts

##### `valid`
True if the checkout is valid, i.e. if the source code was successfully
checked out. False if not, e.g. if its patches failed to apply. Set to
`True` if you successfully checked out a git commit.

Example: `true`

##### `git_repository_url`
The URL of the Git repository which contains the checked out base code.
The shortest possible `https://` URL, or, if that's not available, the
shortest possible `git://` URL.

Example: `"https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"`

##### `git_commit_hash`
The full commit hash of the checked out base code. Note that until a checkout
has the `git_commit_hash` property it may not appear in reports or on the
dashboard.

Example: `"db14560cba31b9fdf8454d097e5cb9e488c621fd"`

##### `patchset_hash`
The full hash of the patches applied on top of the commit, or an empty string,
if there were no patches. Note that until a checkout has the `patchset_hash`
property it may not appear in reports or on the dashboard.

The hash is a sha256 hash over newline-terminated sha256 hashes of each patch,
in order of application. If your patch file alphabetic order matches the
application order (which is true for patches generated with `git format-patch`
or `git send-email`), and you only have the patchset you're hashing in the
current directory, you can generate the hash with this command:

    sha256sum *.patch | cut -c-64 | sha256sum | cut -c-64

Example: `"a86ef57bf15cd35ba4da4e719e0874c8dd9432bb05d9fb5e45b716d43561d2b8"`

##### `start_time`
The time the checkout was started by the CI system. As described by [RFC3339,
5.6 Internet Date/Time Format][datetime_format].

Example: `"2020-08-14T23:08:06.967000+00:00"`

#### Builds

##### `valid`
True if the build is valid, i.e. if it succeeded. False if not.

Example: `true`

##### `architecture`
Target architecture of the build. Not standardized yet.

Example: `"x86_64"`

##### `compiler`
Name and version of the compiler used to make the build.

Example: `"gcc (GCC) 10.1.1 20200507 (Red Hat 10.1.1-1)"`

##### `start_time`
The time the build was started, according to [RFC3339, 5.6 Internet Date/Time
Format][datetime_format].

Example: `"2020-08-14T23:08:10.008000+00:00"`

#### Tests

##### `status`
The test status string, one of the following:

* "FAIL" - the test completed and reported the tested code as faulty.
* "ERROR" - the test didn't complete due to a failure in its code, and the
  status of the tested code is unknown.
* "MISS" - the test didn't run due to a failure in the test harness, and the
  status of both the test and the tested code is unknown.
* "PASS" - the test completed and reported the tested code as correct.
* "DONE" - the test completed and had not reported the status of the tested
  code, but, for example, produced a performance measurement result.
* "SKIP" - the test did not run or complete, because it was not applicable,
  and the status of both the test and the tested code is unknown.

The status names above are listed in priority order (highest to lowest), which
can be used to produce a summary status for a collection of test runs.

For example, the summary status for all testing done on a build would be the
highest-priority status across all its tests.

You can break down the testing stack into three layers: the tested code, the
test, and the harness running the test (and everything above it). With that in
mind, you can then express each status as one of three outcomes for each
layer: failure, success, or no data. Like this:

    STATUS      CODE TEST HARNESS+           LEGEND

    FAIL        ❌   ✅   ✅                 ❌ - failure
    ERROR       ➖   ❌   ✅                 ✅ - success
    MISS        ➖   ➖   ❌                 ➖ - no data
    PASS        ✅   ✅   ✅
    DONE        ➖   ✅   ✅
    SKIP        ➖   ➖   ✅
                ➖   ➖   ➖

E.g. an ERROR status would mean that the harness succeeded in running the
test, but the test code itself failed, and the test didn't complete, so we
cannot make any conclusions about the tested code.

OTOH, the similar DONE status would mean that both the harness and the test
worked alright, but the test simply didn't produce sufficient data to make a
conclusion about the code. E.g. it made a performance measurement that needs
analyzing over a span of revisions (to determine if it's dropping or rising),
and is meaningless alone.

Going one layer up, the MISS status means that the harness has failed to even
execute the test, so it didn't run, and we don't have any data on its outcome,
and obviously no data on the tested code either. And the similar SKIP status
means that the harness worked alright, and either it, or the test itself,
decided not to run this specific test, because it was inapplicable.

Finally, the last line in the table above (without a status) corresponds to
the absent "status" field, and means that the test is either only scheduled,
or is still executing, and so we have no status data yet.

Another way to visualize the status values and the three layered testing stack,
is to put them into an execution outcome chart:

![The image is a flowchart showing test result statuses: "schedule test" leads
  to "SKIP" (test not applicable), "MISS" (test not run, CI maintainer
  responsible), "run test" leads to "DONE" (no result needed), "ERROR" (test
  not completed, test maintainer responsible), then "evaluate result" leads to
  "PASS" (requirements met) or "FAIL" (requirements failed, kernel developer
  responsible).](mapping-test-status-and-responsibility.png)

Example: `"FAIL"`

##### `path`
Dot-separated path to the node in the test classification tree the executed
test belongs to. The empty string signifies the root of the tree, i.e. all
tests for the build, executed by the origin CI system.

Please consult the [catalog of recognized tests][tests] for picking the
top-level name for your test, and submit a PR adding it if you don't find it.

Example: `"ltp.sem01"`

##### `start_time`
The time the test run was started, according to [RFC3339, 5.6 Internet
Date/Time Format][datetime_format].

Example: `"2020-08-14T23:41:54+00:00"`

#### Issues

"Issues" describe an issue with either the kernel code being tested, the test,
or anything running the test, such as test harness, framework, or just the CI
system as a whole.

##### `version`

The version number of the issue (required). The system always uses the issue
with the largest version number, so if you want to change your issue, submit a
new one with the same ID and larger version.

Example: `20240502101105`

##### `report_url`

The URL pointing to the issue report: e.g. an issue in a bug tracker, a
thread on a mailing list, and so on. Anything helping describe and identify
the issue to humans.

Example: `https://bugzilla.kernel.org/show_bug.cgi?id=207065`

##### `report_subject`

The subject, or title of the issue report, helping identify the issue in
reports or dashboards, without following the report URL.

Example: `C-media USB audio device stops working from 5.2.0-rc3 onwards`

##### `culprit`

An object with boolean attributes pointing out the origin, or the "culprit" of
the issue: `code` - if the bug is in the kernel itself, `tool` - if the bug is
in the test, or e.g. the build toolchain, and `harness` - if the bug is in the
test framework, or the CI system in general. These fields help the system
decide who to notify when the issue is discovered somewhere.

A missing attribute would indicate the unknown status (not "false"), so please
include each attribute with a value, when you know it.

Example: `{"code": true, "tool": false, "harness": false}'

#### Incidents

"Incidents" record issue occurrences in builds and tests. They always refer to
a particular version of the issue. This allows the system to use results of
triaging the previous version of the issue, while triaging of the new one is
ongoing.

##### `issue_version`

The version of the issue this incident refers to (required, in addition to
`issue_id`).

Example: `20240502101105`

##### `build_id`

ID of the build the issue was found in, for issues found during a build.

Example: `submitter:32254`

##### `test_id`

ID of the test run the issue was found in, for issues found during a test.

Example: `submitter:114353810`

##### `present`

True if the issue did occur in the linked build or test. False if it did not.
An absent attribute means that the occurence status is unknown, and can
signify ongoing triaging.

Example: `true`

### Extra data
If you have some data you'd like to provide developers with, but the schema
doesn't accommodate it, put it as arbitrary JSON under the `misc` field, which
is supported for every object. Then contact KCIDB developers with your
requirements.

For example, here's a `misc` field from KernelCI-native builds:

```json
{
    "build_platform" : [
        "Linux",
        "build-j7428-x86-64-gcc-8-x86-64-defconfig-wk45x",
        "4.15.0-1092-azure",
        "#102~16.04.1-Ubuntu SMP Tue Jul 14 20:28:23 UTC 2020",
        "x86_64",
        ""
    ],
    "kernel_image_size" : 9042816,
    "vmlinux_bss_size" : 1019904,
    "vmlinux_data_size" : 1595008
}
```

The kernel developers would already be able to see it in the dashboard, and
the KCIDB developers would have samples of your data which would help them
support it in the schema.

You can also put any debugging information you need into the `misc` fields.
E.g. you can add IDs of your internal objects corresponding to reported ones,
so you can track where they came from, like CKI does:

```json
{
    "beaker_recipe_id": 8687594,
    "beaker_task_id": 114353810,
    "job_id": 956777,
    "pipeline_id": 612127
}
```

While the `misc` field is primarily aimed at computers, the `comment` field
for every object can contain free-form text helping people understand the
data.

4\. Submit report data
----------------------
As soon as you have your report data pass validation (e.g. with the
`kcidb-validate` tool), you should be able to submit it to the database.

If you're using shell, and e.g. have your data in file `report.json`, pipe it
to the `kcidb-submit` tool like this:

    kcidb-submit -p kernelci-production \
                 -t playground_kcidb_new < report.json

If you're using Python 3, and e.g. have variable `report` holding standard
JSON representation of your report, you can submit it like this:

```python
import kcidb

client = kcidb.Client(project_id="kernelci-production",
                      topic_name="playground_kcidb_new")
client.submit(report)
```

Your data could take up to a few minutes to reach the database, but after that
you should be able to find it in our [dashboard][dashboard].

### Submitting directly

If for any reason you cannot use the command-line tools, and you don't use
Python 3 (e.g. you are using another language in a "serverless" environment),
you can interface with KCIDB submission system directly.

NOTE: this interface is less stable than the command-line, and the library
interfaces, and is more likely to change in the future.

You will have to use one of the Google Cloud [Pub/Sub client
libraries][pub_sub_libraries] or [service APIs][pub_sub_apis] to publish your
reports to the Pub/Sub topic specified above, using the provided credentials.
Please make sure to validate each report against the schema output by
`kcidb-schema` before publishing it.

### Submitting objects multiple times

If you submit an object with the same ID more than once, then the database
will still consider them as one object, but will pick the value for each of
its properties randomly, from across all submitted objects, wherever present.

This can be used to submit object properties gradually. E.g. you can send a
test object without the `duration` and `status` properties when you start the
test. Then, when it finishes, you can send a report with a test containing the
same `id`, and only the `duration` and `status` properties, to mark its
completion.

5\. Go to 3, if you have more
------------------------------
Do not hesitate to start submitting your reports as soon as you can. This will
let you, kernel developers, and KCIDB developers see how it works, what
changes/additions might be needed to both your data and KCIDB, and improve our
reporting faster!

[datetime_format]: https://tools.ietf.org/html/rfc3339#section-5.6
[tests]: https://github.com/kernelci/kcidb/blob/master/tests.yaml
[dashboard]: https://kcidb.kernelci.org/
[pub_sub_libraries]: https://cloud.google.com/pubsub/docs/reference/libraries
[pub_sub_apis]: https://cloud.google.com/pubsub/docs/reference/service_apis_overview

### Migration from legacy Pub/Sub to REST API

The legacy Pub/Sub API is deprecated and will be removed in the future. The REST API is the recommended way to interact with KCIDB.

If you are using kcidb as a library, or the `kcidb-submit` tool, you can switch to the REST API by setting the `KCIDB_REST` environment variable to the appropriate endpoint with token.
```bash
export KCIDB_REST="https://token@db.kernelci.org/"
```

After setting the environment variable, you can use the same commands as before, and they will automatically use the REST API instead of the legacy Pub/Sub API.
