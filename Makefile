SPEC := i3-settings-qubes.spec

install:
	install -m 644 -D i3.config $(DESTDIR)/etc/i3/config.qubes
	install -m 644 -D i3.config.keycodes $(DESTDIR)/etc/i3/config.keycodes.qubes
	install -m 755 -D qubes-i3-sensible-terminal $(DESTDIR)/usr/bin/qubes-i3-sensible-terminal
	install -m 755 -D qubes-i3-xdg-autostart $(DESTDIR)/usr/bin/qubes-i3-xdg-autostart
	install -m 755 -D qubes-i3status.py $(DESTDIR)/usr/bin/qubes-i3status

clean:
	rm -rf debian/changelog.*
	rm -rf pkgs
