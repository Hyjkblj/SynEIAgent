package com.tgrobot.mobile.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val RobotColorScheme = lightColorScheme(
    primary = OceanBlue,
    onPrimary = Sand,
    secondary = SeaGreen,
    onSecondary = Sand,
    tertiary = Coral,
    background = Sand,
    onBackground = Ink,
    surface = Mist,
    onSurface = Ink,
    error = Coral,
)

@Composable
fun RobotAppTheme(
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = RobotColorScheme,
        typography = Typography(),
        content = content,
    )
}
