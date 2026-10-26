# Team access

Team access uses individual SSH public keys and a locked forwarding-only Linux
account. It does not expose the CRM or noVNC to the public internet.

1. Send the teammate the two `.command` files.
2. They run `1-create-access-key.command` and send you the copied **public** key.
3. Add that public key to `/home/phone-shi-team/.ssh/authorized_keys` on the VDS.
4. They run `2-open-phone-shi.command` whenever they want the CRM and viewer.

On first use, macOS may require Control-click → Open because the files came
from another computer. Both launchers use only built-in macOS `ssh`, `open`,
`curl`, `grep`, and `pbcopy` commands; nothing else is installed.

Never exchange private keys. Remove one line from `authorized_keys` to revoke
one teammate without disrupting anyone else.
