# Team access

Team access uses individual SSH public keys and a locked forwarding-only Linux
account. It does not expose the CRM or noVNC to the public internet.

1. Send the teammate `Phone Shi CRM.app` (normally inside the supplied ZIP).
2. They open the app once. It creates an access key and copies the **public**
   key; they send that copied line to you.
3. Add that public key to `/home/phone-shi-team/.ssh/authorized_keys` on the VDS.
4. They open `Phone Shi CRM.app` again. From then on the app automatically
   starts the secure connection and opens the CRM and phone viewer.

On first use, macOS may require Control-click → Open because the app came from
another computer. The app uses only built-in macOS commands; nothing else is
installed. The two `.command` files are retained as recovery tools.

Never exchange private keys. Remove one line from `authorized_keys` to revoke
one teammate without disrupting anyone else.
