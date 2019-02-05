# Contribution guidelines
Thank you for considering contributing to this project! The following are guidelines you need to follow.

## GPG commit signature verification
To ensure your work comes from a trusted source, you are required to sign your commits with a GPG key that you generate yourself. You can read [this article from GitHub](https://help.github.com/articles/signing-commits/) as a guide.

**Commits that do not have a cryptograhically verifiable signature will not be accepted.**

## Developer Certificate of Origin
In order to give project's owner permission to use and redistribute your contributions as part of the project, you must accept the Developer Certificate of Origin (DCO):

    By making a contribution to this project, I certify that:
    
    (a) The contribution was created in whole or in part by me and I
        have the right to submit it under the open source license
        indicated in the file; or
    
    (b) The contribution is based upon previous work that, to the best
        of my knowledge, is covered under an appropriate open source
        license and I have the right under that license to submit that
        work with modifications, whether created in whole or in part
        by me, under the same open source license (unless I am
        permitted to submit under a different license), as indicated
        in the file; or
    
    (c) The contribution was provided directly to me by some other
        person who certified (a), (b) or (c) and I have not modified
        it.
    
    (d) I understand and agree that this project and the contribution
        are public and that a record of the contribution (including all
        personal information I submit with it, including my sign-off) is
        maintained indefinitely and may be redistributed consistent with
        this project or the open source license(s) involved.

In order to accept the DCO, contributor's commit message should have a line in the end like this:

    Signed-off-by: John Smith <john@example.com>

This can be done with a ```--signoff``` option either to ```git commit``` if you are signing-off a single commit or to ```git rebase``` if you are signing-off all commits in a pull request.

**By submitting signed-off contribution to this project you accept the Developer Certificate of Origin.**