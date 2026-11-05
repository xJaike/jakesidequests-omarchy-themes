import QtQuick
import Quickshell
import qs.Ui
import qs.Commons as Commons

BarWidget {
    id: root
    moduleName: "io.github.xjaike.theme-collection"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

    BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: "\uf1fc"
        tooltipText: strings.t("picker.open")
        onPressed: {
            const script = decodeURIComponent(Qt.resolvedUrl("theme_picker.py").toString().replace(/^file:\/\//, ""))
            Quickshell.execDetached(["omarchy", "launch", "terminal", "python", script])
        }
    }
}
