"""App menu naming and About panel for Image Lab on macOS."""

from __future__ import annotations

import os

ABOUT_TEXT = """\
Version {version}

Fast, private batch image compression for your Mac.

Compress, convert and resize hundreds of photos at once — to a target file size, a quality level, or losslessly.

• Your images never leave this Mac
• No account, no subscription, no upload limits
• Works fully offline

© 2026 Image Lab. MIT License.\
"""

_about_delegate = None


def _version() -> str:
    try:
        import AppKit

        info = AppKit.NSBundle.mainBundle().infoDictionary() or {}
        return str(info.get("CFBundleShortVersionString") or os.environ.get("IMAGE_LAB_VERSION", "dev"))
    except Exception:  # noqa: BLE001
        return os.environ.get("IMAGE_LAB_VERSION", "dev")


def show_about_panel() -> None:
    import AppKit

    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_("Image Lab")
    alert.setInformativeText_(ABOUT_TEXT.format(version=_version()))
    alert.setAlertStyle_(AppKit.NSInformationalAlertStyle)
    alert.addButtonWithTitle_("OK")
    alert.runModal()


def patch_bundle_display_name(app_name: str) -> None:
    try:
        import AppKit

        info = AppKit.NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = app_name
            info["CFBundleDisplayName"] = app_name
    except Exception:  # noqa: BLE001
        pass


def configure_app_menu(app_name: str) -> None:
    """Replace 'Python' in the app menu and route About to our panel. Safe to call repeatedly."""
    try:
        from PyObjCTools import AppHelper

        AppHelper.callAfter(_configure, app_name)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not configure the app menu: {exc}", flush=True)


def _configure(app_name: str) -> None:
    global _about_delegate

    import AppKit
    from Foundation import NSObject, NSProcessInfo

    NSProcessInfo.processInfo().setProcessName_(app_name)
    main_menu = AppKit.NSApplication.sharedApplication().mainMenu()
    if not main_menu or main_menu.numberOfItems() == 0:
        return
    app_item = main_menu.itemAtIndex_(0)
    submenu = app_item.submenu() if app_item is not None else None
    if submenu is None:
        return
    app_item.setTitle_(app_name)
    submenu.setTitle_(app_name)
    for index in range(submenu.numberOfItems()):
        item = submenu.itemAtIndex_(index)
        if item is not None and "Python" in str(item.title()):
            item.setTitle_(str(item.title()).replace("Python", app_name))

    if _about_delegate is None:

        class AboutDelegate(NSObject):
            def showAbout_(self, sender) -> None:
                show_about_panel()

        _about_delegate = AboutDelegate.alloc().init()
    about_item = submenu.itemAtIndex_(0)
    if about_item is not None:
        about_item.setTitle_(f"About {app_name}")
        about_item.setTarget_(_about_delegate)
        about_item.setAction_("showAbout:")
