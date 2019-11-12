# Contribution guidelines
Thank you for considering contributing to this project! The following are guidelines you need to follow.

## Code style
To make sure your code style is consistent with project's code style, use [pre-commit](https://pre-commit.com/) which will automatically run formatters and linting tools before any commit:
```bash
pip install -r requirements-dev.txt
pre-commit install
git commit
```
If any staged file is reformatted, you need to stage it again. If linting errors are found, you need to fix them before staging again.

## GPG commit signature verification
To ensure your work comes from a trusted source, you are required to sign your commits with a GPG key that you generate yourself. You can read [this article from GitHub](https://help.github.com/articles/signing-commits/) as a guide.

**Commits that do not have a cryptographically verifiable signature will not be accepted.**

## Contributor License Agreement
In order to give project's owner permission to use and redistribute your contributions as part of the project, you must accept the [Contributor License Agreement](https://github.com/fincubator/tellerbot/blob/master/CLA.md) (CLA):

To accept the CLA, contributors should:

  - declare the agreement with its terms in the comment to the pull request
  - have a line like this with contributor's name and e-mail address in the end of every commit message:
    ```Signed-off-by: John Smith <john@example.com>```

The latter can be done with a ```--signoff``` option either to ```git commit``` if you are signing-off a single commit or to ```git rebase``` if you are signing-off all commits in a pull request.

**Contributions without agreement with the terms of Contributor License Agreement will not be accepted.**
